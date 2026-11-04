"""Healthcheck usado por Docker Compose; verifica también TLS."""

import argparse
import os
import ssl
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=["v1", "v2", "log"])
    args = parser.parse_args()
    certificate = Path(os.getenv("TLS_CERT_FILE", "certs/server.crt"))
    if args.service == "log":
        import grpc

        from shortener.generated import hits_pb2, hits_pb2_grpc

        credentials = grpc.ssl_channel_credentials(certificate.read_bytes())
        with grpc.secure_channel("localhost:50051", credentials) as channel:
            response = hits_pb2_grpc.HitLoggerStub(channel).Ping(hits_pb2.PingRequest(), timeout=2)
            if response.status != "ok":
                raise RuntimeError("Log no disponible")
    else:
        port = 8443 if args.service == "v1" else 8444
        context = ssl.create_default_context(cafile=str(certificate))
        with urllib.request.urlopen(
            f"https://localhost:{port}/health", context=context, timeout=2
        ) as response:
            if response.status != 200:
                raise RuntimeError("HTTP no disponible")


if __name__ == "__main__":
    main()
