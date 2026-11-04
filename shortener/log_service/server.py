"""Servicio gRPC independiente con TLS y persistencia antes del ACK."""

import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

import grpc

from shortener.common.base62 import is_valid_hash
from shortener.generated import hits_pb2, hits_pb2_grpc
from shortener.log_service.repository import LogRepository

LOGGER = logging.getLogger(__name__)


class HitLogger(hits_pb2_grpc.HitLoggerServicer):
    def __init__(self, repository: LogRepository):
        self.repository = repository

    def LogHit(self, request, context):
        try:
            UUID(request.event_id)
            if (
                not request.HasField("timestamp")
                or not request.short_url.startswith("https://")
                or not request.long_url.startswith(("http://", "https://"))
                or not is_valid_hash(request.hash)
            ):
                raise ValueError("Evento incompleto")
            timestamp = request.timestamp.ToJsonString()
        except (ValueError, OverflowError) as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        try:
            inserted = self.repository.add(
                request.event_id, timestamp, request.short_url, request.long_url, request.hash
            )
        except sqlite3.Error:
            LOGGER.exception("No se pudo persistir el evento")
            context.abort(grpc.StatusCode.UNAVAILABLE, "Log DB no disponible")
        return hits_pb2.LogReply(recorded=inserted)

    def Ping(self, request, context):
        try:
            self.repository.check()
        except sqlite3.Error:
            context.abort(grpc.StatusCode.UNAVAILABLE, "Log DB no disponible")
        return hits_pb2.PingReply(status="ok")


def create_server(db_path: Path, cert_file: Path, key_file: Path, address: str):
    repository = LogRepository(db_path)
    repository.initialize()
    server = grpc.server(
        ThreadPoolExecutor(max_workers=8),
        options=[("grpc.max_receive_message_length", 32768)],
    )
    hits_pb2_grpc.add_HitLoggerServicer_to_server(HitLogger(repository), server)
    credentials = grpc.ssl_server_credentials([(key_file.read_bytes(), cert_file.read_bytes())])
    port = server.add_secure_port(address, credentials)
    if not port:
        raise RuntimeError(f"No se pudo abrir el puerto gRPC: {address}")
    return server, port
