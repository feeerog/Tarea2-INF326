"""Arquitectura 1: HTTP 302 sin caché + evento de visita por gRPC."""

from contextlib import asynccontextmanager

from litestar import Litestar, Request, get
from litestar.datastructures import State
from litestar.openapi import OpenAPIConfig
from litestar.params import FromPath
from litestar.response import Redirect

from shortener.common.config import Settings
from shortener.common.database import UrlRepository
from shortener.common.http import create_url, health, resolve, stats
from shortener.v1.grpc_client import LogClient


def create_app(settings: Settings | None = None) -> Litestar:
    settings = settings or Settings.from_env("v1")
    repository = UrlRepository(settings.db_path)

    @asynccontextmanager
    async def lifespan(app: Litestar):
        repository.initialize()
        app.state.log_client = LogClient(settings)
        try:
            yield
        finally:
            app.state.log_client.close()

    @get("/{code:str}", status_code=302, cache=False, sync_to_thread=True)
    def redirect_url(code: FromPath[str], request: Request) -> Redirect:
        record = resolve(request, code)
        if request.method == "GET":
            request.app.state.log_client.record(record)
        return Redirect(
            path=record.long_url,
            status_code=302,
            headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"},
        )

    return Litestar(
        [create_url, redirect_url, health, stats],
        state=State({"settings": settings, "repository": repository}),
        lifespan=[lifespan],
        request_max_body_size=16384,
        openapi_config=OpenAPIConfig(title="Shortener v1 - 302 + gRPC", version="1.0.0"),
    )
