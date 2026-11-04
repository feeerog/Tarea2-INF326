"""Configuración por variables de entorno; los valores por defecto son locales."""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    version: str
    db_path: Path
    base_url: str
    cert_file: Path = Path("certs/server.crt")
    key_file: Path = Path("certs/server.key")
    grpc_target: str = "localhost:50051"
    grpc_timeout: float = 0.5
    rate_limit: int = 60
    cache_ttl: int = 60
    browser_cache_ttl: int = 300

    def __post_init__(self) -> None:
        if self.version not in {"v1", "v2"}:
            raise ValueError("Versión inválida")
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.username
        ):
            raise ValueError("BASE_URL debe ser un origen HTTPS, sin ruta ni credenciales")
        if (
            self.grpc_timeout <= 0
            or min(self.rate_limit, self.cache_ttl, self.browser_cache_ttl) <= 0
        ):
            raise ValueError("Los límites, TTL y timeout deben ser mayores que cero")

    @classmethod
    def from_env(cls, version: str) -> "Settings":
        port = 8443 if version == "v1" else 8444
        return cls(
            version=version,
            db_path=Path(os.getenv("DB_PATH", f"data/shortener_{version}.sqlite3")),
            base_url=os.getenv("BASE_URL", f"https://localhost:{port}").rstrip("/"),
            cert_file=Path(os.getenv("TLS_CERT_FILE", "certs/server.crt")),
            key_file=Path(os.getenv("TLS_KEY_FILE", "certs/server.key")),
            grpc_target=os.getenv("GRPC_TARGET", "localhost:50051"),
            grpc_timeout=float(os.getenv("GRPC_TIMEOUT_SECONDS", "0.5")),
            rate_limit=int(os.getenv("RATE_LIMIT_PER_MINUTE", "60")),
            cache_ttl=int(os.getenv("CACHE_TTL_SECONDS", "60")),
            browser_cache_ttl=int(os.getenv("BROWSER_CACHE_TTL_SECONDS", "300")),
        )
