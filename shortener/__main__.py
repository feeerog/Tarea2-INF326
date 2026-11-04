"""Entradas ejecutables: python -m shortener {v1,v2,log}."""

import argparse
import logging
import os
from pathlib import Path

import uvicorn

from shortener.common.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Tarea 2 INF326")
    parser.add_argument("service", choices=["v1", "v2", "log"])
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    if args.service == "log":
        from shortener.log_service.server import create_server

        server, port = create_server(
            Path(os.getenv("LOG_DB_PATH", "data/log.sqlite3")),
            Path(os.getenv("TLS_CERT_FILE", "certs/server.crt")),
            Path(os.getenv("TLS_KEY_FILE", "certs/server.key")),
            os.getenv("GRPC_BIND", "127.0.0.1:50051"),
        )
        server.start()
        logging.info("Log gRPC con TLS escuchando en puerto %s", port)
        try:
            server.wait_for_termination()
        except KeyboardInterrupt:
            server.stop(grace=3).wait()
        return

    settings = Settings.from_env(args.service)
    if args.service == "v1":
        from shortener.v1.app import create_app
    else:
        from shortener.v2.app import create_app
    uvicorn.run(
        create_app(settings),
        host=os.getenv("HTTP_HOST", "127.0.0.1"),
        port=int(os.getenv("HTTP_PORT", "8443" if args.service == "v1" else "8444")),
        ssl_certfile=str(settings.cert_file),
        ssl_keyfile=str(settings.key_file),
        # Un proceso: los stores en memoria pertenecen a esta instancia.
        workers=1,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
