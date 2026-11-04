from uuid import uuid4

import grpc
import pytest

from shortener.common.database import connection
from shortener.generated import hits_pb2, hits_pb2_grpc


def test_logger_tls_ping_persistence_and_idempotence(grpc_service, certificates):
    target, path = grpc_service
    credentials = grpc.ssl_channel_credentials(certificates[0].read_bytes())
    with grpc.secure_channel(target, credentials) as channel:
        stub = hits_pb2_grpc.HitLoggerStub(channel)
        assert stub.Ping(hits_pb2.PingRequest(), timeout=2).status == "ok"
        event = hits_pb2.UrlHit(
            event_id=str(uuid4()),
            short_url="https://localhost:8443/eRgfR",
            long_url="https://usm.cl/",
            hash="eRgfR",
        )
        event.timestamp.GetCurrentTime()
        assert stub.LogHit(event, timeout=2).recorded is True
        assert stub.LogHit(event, timeout=2).recorded is False
    with connection(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM hits").fetchone()[0] == 1


def test_logger_rejects_incomplete_event(grpc_service, certificates):
    credentials = grpc.ssl_channel_credentials(certificates[0].read_bytes())
    with grpc.secure_channel(grpc_service[0], credentials) as channel:
        stub = hits_pb2_grpc.HitLoggerStub(channel)
        with pytest.raises(grpc.RpcError) as error:
            stub.LogHit(hits_pb2.UrlHit(), timeout=2)
        assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT
