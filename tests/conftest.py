from pathlib import Path

import grpc
import pytest

from scripts.generate_certs import generate
from shortener.log_service.server import create_server


@pytest.fixture(scope="session")
def certificates(tmp_path_factory):
    return generate(tmp_path_factory.mktemp("tls"))


@pytest.fixture
def grpc_service(tmp_path: Path, certificates):
    cert, key = certificates
    db_path = tmp_path / "hits.sqlite3"
    server, port = create_server(db_path, cert, key, "127.0.0.1:0")
    server.start()
    target = f"localhost:{port}"
    credentials = grpc.ssl_channel_credentials(cert.read_bytes())
    with grpc.secure_channel(target, credentials) as channel:
        grpc.channel_ready_future(channel).result(timeout=5)
    try:
        yield target, db_path
    finally:
        server.stop(grace=0).wait()
