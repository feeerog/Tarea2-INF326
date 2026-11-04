"""Cliente gRPC reutilizado, con deadline y política de fallo explícita."""

import logging
from threading import Lock
from uuid import uuid4

import grpc

from shortener.common.config import Settings
from shortener.common.database import UrlRecord
from shortener.generated import hits_pb2, hits_pb2_grpc

LOGGER = logging.getLogger(__name__)


class LogClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        credentials = grpc.ssl_channel_credentials(
            root_certificates=settings.cert_file.read_bytes()
        )
        self.channel = grpc.secure_channel(settings.grpc_target, credentials)
        self.stub = hits_pb2_grpc.HitLoggerStub(self.channel)
        self.logged = 0
        self.failed = 0
        self._lock = Lock()

    def record(self, record: UrlRecord) -> None:
        event = hits_pb2.UrlHit(
            event_id=str(uuid4()),
            short_url=f"{self.settings.base_url.rstrip('/')}/{record.hash}",
            long_url=record.long_url,
            hash=record.hash,
        )
        event.timestamp.GetCurrentTime()
        try:
            self.stub.LogHit(event, timeout=self.settings.grpc_timeout)
            with self._lock:
                self.logged += 1
        except grpc.RpcError as exc:
            # Se prioriza que la persona llegue a la URL. No hay cola durable:
            # una caída del logger puede perder este evento. Ver DISCUSION.md.
            with self._lock:
                self.failed += 1
            LOGGER.warning("Evento %s sin ACK gRPC (%s)", event.event_id, exc.code().name)

    def close(self) -> None:
        self.channel.close()
