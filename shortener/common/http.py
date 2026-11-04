"""Contrato HTTP compartido por las dos implementaciones."""

from dataclasses import dataclass
from urllib.parse import urlsplit

from litestar import Request, Response, get, post
from litestar.exceptions import NotFoundException, ValidationException
from litestar.params import JSONBody

from shortener.common.base62 import is_valid_hash
from shortener.common.database import UrlRecord


@dataclass
class CreateUrl:
    url: str


def validate_url(value: str) -> str:
    if not value or len(value) > 8192:
        raise ValidationException("La URL debe tener entre 1 y 8192 caracteres")
    if any(ord(char) <= 32 or ord(char) == 127 for char in value) or "\\" in value:
        raise ValidationException("La URL no debe contener espacios ni caracteres de control")
    try:
        parsed = urlsplit(value)
        port = parsed.port  # Obliga a validar puertos mal formados o fuera de rango.
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or port == 0
        ):
            raise ValueError
        parsed.hostname.encode("idna")
        if "%" in parsed.hostname:
            raise ValueError
    except (ValueError, UnicodeError) as exc:
        raise ValidationException(
            "Se requiere una URL http:// o https:// válida, sin credenciales"
        ) from exc
    return value


@post("/urls", status_code=201, sync_to_thread=True)
def create_url(data: JSONBody[CreateUrl], request: Request) -> Response:
    record = request.app.state.repository.create(validate_url(data.url))
    short_url = f"{request.app.state.settings.base_url.rstrip('/')}/{record.hash}"
    return Response(
        content={
            "id": record.id,
            "hash": record.hash,
            "long_url": record.long_url,
            "short_url": short_url,
        },
        status_code=201,
        headers={"Location": short_url, "Cache-Control": "no-store"},
    )


def resolve(request: Request, code: str) -> UrlRecord:
    if not is_valid_hash(code):
        raise NotFoundException("URL corta inexistente")
    record = request.app.state.repository.get(code)
    if record is None:
        raise NotFoundException("URL corta inexistente")
    return record


@get("/health", sync_to_thread=True)
def health(request: Request) -> dict:
    request.app.state.repository.check()
    return {"status": "ok", "architecture": request.app.state.settings.version}


@get("/stats", sync_to_thread=False, cache=False)
def stats(request: Request) -> Response:
    state = request.app.state
    values = {"architecture": state.settings.version, "db_lookups": state.repository.lookup_count}
    if state.settings.version == "v2":
        values.update(cache_hits=state.cache.hits, cache_misses=state.cache.misses)
    else:
        values.update(grpc_logged=state.log_client.logged, grpc_failed=state.log_client.failed)
    return Response(values, headers={"Cache-Control": "no-store"})
