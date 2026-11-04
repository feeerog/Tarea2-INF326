"""Arquitectura 2: HTTP 301, rate limiter y caché de respuestas de Litestar."""

from contextlib import asynccontextmanager
from datetime import timedelta

import anyio
from litestar import Litestar, Request, get
from litestar.config.response_cache import ResponseCacheConfig
from litestar.datastructures import State
from litestar.middleware.rate_limit import RateLimitConfig
from litestar.openapi import OpenAPIConfig
from litestar.params import FromPath
from litestar.response import Redirect
from litestar.stores.memory import MemoryStore
from litestar.types import HTTPScope

from shortener.common.config import Settings
from shortener.common.database import UrlRepository
from shortener.common.http import create_url, health, resolve, stats


class MeasuredMemoryStore(MemoryStore):
    """Solo añade contadores; Litestar sigue administrando clave, datos y TTL."""

    def __init__(self):
        super().__init__()
        self.hits = 0
        self.misses = 0

    async def get(self, key: str, renew_for: int | timedelta | None = None) -> bytes | None:
        value = await super().get(key, renew_for=renew_for)
        if value is None:
            self.misses += 1
        else:
            self.hits += 1
        return value


def cache_redirects_only(scope: HTTPScope, status_code: int) -> bool:
    # Ni errores 404/429 ni POST ni HEAD se almacenan como respuestas GET.
    return scope["method"] == "GET" and status_code == 301


def create_app(settings: Settings | None = None) -> Litestar:
    settings = settings or Settings.from_env("v2")
    repository = UrlRepository(settings.db_path)
    response_store = MeasuredMemoryStore()
    rate_store = MemoryStore()

    @asynccontextmanager
    async def lifespan(app: Litestar):
        repository.initialize()

        async def cleanup_expired() -> None:
            while True:
                await anyio.sleep(30)
                await response_store.delete_expired()
                await rate_store.delete_expired()

        async with anyio.create_task_group() as group:
            group.start_soon(cleanup_expired)
            try:
                yield
            finally:
                group.cancel_scope.cancel()
        await response_store.delete_all()
        await rate_store.delete_all()

    @get("/{code:str}", status_code=301, cache=True, sync_to_thread=True)
    def redirect_url(code: FromPath[str], request: Request) -> Redirect:
        record = resolve(request, code)
        return Redirect(
            path=record.long_url,
            status_code=301,
            headers={"Cache-Control": f"public, max-age={settings.browser_cache_ttl}"},
        )

    limiter = RateLimitConfig(
        rate_limit=("minute", settings.rate_limit),
        exclude=[r"^/health$", r"^/stats$", r"^/schema(?:/.*)?$"],
        store="rate_limit",
    )
    return Litestar(
        [create_url, redirect_url, health, stats],
        state=State({"settings": settings, "repository": repository, "cache": response_store}),
        lifespan=[lifespan],
        middleware=[limiter.middleware],
        stores={"response_cache": response_store, "rate_limit": rate_store},
        response_cache_config=ResponseCacheConfig(
            default_expiration=settings.cache_ttl,
            store="response_cache",
            cache_response_filter=cache_redirects_only,
        ),
        request_max_body_size=16384,
        openapi_config=OpenAPIConfig(
            title="Shortener v2 - 301 + cache + rate limit", version="1.0.0"
        ),
    )
