import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from litestar.testing import TestClient

from shortener.common.base62 import INITIAL_ID
from shortener.common.config import Settings
from shortener.common.database import connection
from shortener.v1.app import create_app as v1_app
from shortener.v2.app import create_app as v2_app


@pytest.fixture(params=["v1", "v2"])
def client(request, tmp_path, certificates, grpc_service):
    cert, key = certificates
    target, _ = grpc_service
    settings = Settings(
        version=request.param,
        db_path=tmp_path / f"{request.param}.db",
        base_url="https://localhost:8443" if request.param == "v1" else "https://localhost:8444",
        cert_file=cert,
        key_file=key,
        grpc_target=target,
    )
    with TestClient(v1_app(settings) if request.param == "v1" else v2_app(settings)) as value:
        yield value


def test_post_and_redirect_contract(client):
    response = client.post("/urls", json={"url": "https://usm.cl/postgrado?campus=sanjoaquin#info"})
    assert response.status_code == 201
    record = response.json()
    assert record["id"] == INITIAL_ID
    assert record["hash"] == "eRgfR"
    assert response.headers["location"] == record["short_url"]
    assert record["short_url"].endswith("/eRgfR")
    redirect = client.get("/eRgfR", follow_redirects=False)
    expected = 302 if client.app.state.settings.version == "v1" else 301
    assert redirect.status_code == expected
    assert redirect.headers["location"] == record["long_url"]
    assert client.get("/notFound", follow_redirects=False).status_code == 404
    assert client.get("/bad-hash", follow_redirects=False).status_code == 404


@pytest.mark.parametrize(
    "url",
    [
        "",
        "usm.cl",
        "javascript:alert(1)",
        "ftp://usm.cl",
        "https://",
        "https:///ruta",
        "https://usm.cl:99999/",
        "https://usuario:clave@usm.cl/",
        "https://usm.cl/a b",
        "https://usm.cl/\r\nX-Foo:bar",
        "https://usm.cl\\@evil.example/",
        "https://%ff/",
        "https://usm.cl/" + "a" * 8192,
    ],
)
def test_invalid_url_rejected(client, url):
    assert client.post("/urls", json={"url": url}).status_code == 400


@pytest.mark.parametrize("payload", [{}, {"url": None}, {"url": ["https://usm.cl"]}])
def test_invalid_json_schema_rejected(client, payload):
    assert client.post("/urls", json=payload).status_code == 400


@pytest.mark.parametrize("client", ["v1"], indirect=True)
def test_v1_each_get_logs_real_grpc_event_and_head_does_not(client, grpc_service):
    record = client.post("/urls", json={"url": "https://usm.cl/"}).json()
    for _ in range(2):
        response = client.get("/" + record["hash"], follow_redirects=False)
        assert response.status_code == 302
        assert "no-store" in response.headers["cache-control"]
    # El contrato implementa GET; HEAD no está habilitado ni genera una visita.
    assert client.head("/" + record["hash"], follow_redirects=False).status_code == 405
    with connection(grpc_service[1]) as conn:
        hits = conn.execute("SELECT * FROM hits ORDER BY id").fetchall()
    assert len(hits) == 2
    assert hits[0]["event_id"] != hits[1]["event_id"]
    for hit in hits:
        assert hit["timestamp"].endswith("Z")
        assert hit["short_url"] == record["short_url"]
        assert hit["long_url"] == record["long_url"]
    assert client.get("/stats").json()["grpc_logged"] == 2


def make_v2(tmp_path, **kwargs):
    return v2_app(
        Settings(
            version="v2", db_path=tmp_path / "v2.db", base_url="https://localhost:8444", **kwargs
        )
    )


def test_cache_hit_bypasses_database_and_separates_urls(tmp_path):
    app = make_v2(tmp_path)
    with TestClient(app) as client:
        a = client.post("/urls", json={"url": "https://usm.cl/a"}).json()["hash"]
        b = client.post("/urls", json={"url": "https://usm.cl/b"}).json()["hash"]
        for code, target in [(a, "a"), (a, "a"), (b, "b"), (a, "a"), (b, "b")]:
            response = client.get("/" + code, follow_redirects=False)
            assert response.status_code == 301
            assert response.headers["location"] == f"https://usm.cl/{target}"
            assert response.headers["cache-control"] == "public, max-age=300"
        result = client.get("/stats").json()
        assert result == {"architecture": "v2", "db_lookups": 2, "cache_hits": 3, "cache_misses": 2}


def test_cache_ttl_expires_and_404_is_not_cached(tmp_path):
    app = make_v2(tmp_path, cache_ttl=1)
    with TestClient(app) as client:
        code = client.post("/urls", json={"url": "https://usm.cl/"}).json()["hash"]
        client.get("/" + code, follow_redirects=False)
        client.get("/" + code, follow_redirects=False)
        assert app.state.repository.lookup_count == 1
        time.sleep(1.1)
        client.get("/" + code, follow_redirects=False)
        assert app.state.repository.lookup_count == 2
        for _ in range(2):
            assert client.get("/unknown", follow_redirects=False).status_code == 404
        assert app.state.repository.lookup_count == 4


def test_rate_limit_counts_posts_and_cache_hits_and_blocks_spoofed_ip(tmp_path):
    app = make_v2(tmp_path, rate_limit=3)
    with TestClient(app) as client:
        code = client.post("/urls", json={"url": "https://usm.cl/"}).json()["hash"]
        for remaining in [1, 0]:
            response = client.get("/" + code, follow_redirects=False)
            assert response.status_code == 301
            assert response.headers["ratelimit-remaining"] == str(remaining)
        blocked = client.get(
            "/" + code, headers={"X-Forwarded-For": "203.0.113.12"}, follow_redirects=False
        )
        assert blocked.status_code == 429
        assert blocked.headers["ratelimit-limit"] == "3"
        assert blocked.headers["ratelimit-remaining"] == "0"
        assert int(blocked.headers["ratelimit-reset"]) > 0
        assert client.get("/health").status_code == 200
        assert client.get("/stats").json()["cache_hits"] == 1
        assert app.state.repository.lookup_count == 1


def test_rate_limit_concurrent_burst_is_bounded(tmp_path):
    app = make_v2(tmp_path, rate_limit=5)
    with TestClient(app) as client:
        code = client.post("/urls", json={"url": "https://usm.cl/"}).json()["hash"]
        with ThreadPoolExecutor(max_workers=12) as pool:
            codes = list(
                pool.map(
                    lambda _: client.get("/" + code, follow_redirects=False).status_code, range(20)
                )
            )
        assert codes.count(301) == 4
        assert codes.count(429) == 16


def test_logger_failure_does_not_prevent_302(tmp_path, certificates):
    cert, key = certificates
    settings = Settings(
        "v1", tmp_path / "v1.db", "https://localhost:8443", cert_file=cert, key_file=key
    )

    from shortener.log_service.server import create_server

    server, port = create_server(tmp_path / "log.db", cert, key, "127.0.0.1:0")
    server.start()
    server.stop(0).wait()
    settings = replace(settings, grpc_target=f"localhost:{port}", grpc_timeout=0.05)
    with TestClient(v1_app(settings)) as client:
        code = client.post("/urls", json={"url": "https://usm.cl/"}).json()["hash"]
        start = time.monotonic()
        response = client.get("/" + code, follow_redirects=False)
        assert response.status_code == 302
        assert time.monotonic() - start < 2
        result = client.get("/stats").json()
        assert result["grpc_failed"] == 1
        assert result["grpc_logged"] == 0
