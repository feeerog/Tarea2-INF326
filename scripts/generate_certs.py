"""Certificado autofirmado de desarrollo para HTTPS y gRPC/TLS."""

import argparse
import ipaddress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def generate(output: Path, force: bool = False) -> tuple[Path, Path]:
    output.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = output / "server.crt", output / "server.key"
    if not force and cert_path.exists() and key_path.exists():
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        if cert.not_valid_after_utc <= datetime.now(UTC) + timedelta(days=1):
            raise RuntimeError("Certificado vencido o próximo a vencer: regenerar con --force")
        return cert_path, key_path
    if not force and (cert_path.exists() or key_path.exists()):
        raise RuntimeError("Par de certificado/clave incompleto: revisar o usar --force")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "INF326 localhost")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName(host)
                    for host in ("localhost", "shortener-v1", "shortener-v2", "log-service")
                ]
                + [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ("127.0.0.1", "::1")]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("certs"))
    parser.add_argument("--force", action="store_true", help="Reemplazar el par existente")
    args = parser.parse_args()
    cert, _ = generate(args.output, args.force)
    print(f"Certificado listo: {cert}; la clave privada no debe subirse al repositorio.")


if __name__ == "__main__":
    main()
