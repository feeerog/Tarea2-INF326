"""Prueba de extremo a extremo: tres procesos, sockets, TLS y bases reales."""

import os
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path

import grpc
import httpx
import pytest

from scripts.smoke import verify_services
from shortener.common.database import connection

ROOT = Path(__file__).resolve().parents[1]


def unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def test_real_https_grpc_cache_limit_and_restart(tmp_path, certificates):
    cert, key = certificates
    ports = set()
    while len(ports) < 3:
        ports.add(unused_port())
    log_port, v1_port, v2_port = sorted(ports)
    environment = {
        **os.environ,
        "TLS_CERT_FILE": str(cert),
        "TLS_KEY_FILE": str(key),
        "GRPC_BIND": f"127.0.0.1:{log_port}",
        "GRPC_TARGET": f"localhost:{log_port}",
        "LOG_DB_PATH": str(tmp_path / "log.db"),
        "HTTP_HOST": "127.0.0.1",
        "RATE_LIMIT_PER_MINUTE": "8",
        "CACHE_TTL_SECONDS": "60",
        "BROWSER_CACHE_TTL_SECONDS": "300",
    }
    processes = []
    handles = []

    def start(service, port=None):
        env = dict(environment)
        if port:
            env.update(
                HTTP_PORT=str(port),
                BASE_URL=f"https://localhost:{port}",
                DB_PATH=str(tmp_path / f"{service}.db"),
            )
        handle = (tmp_path / f"{service}-{len(processes)}.log").open("w")
        handles.append(handle)
        process = subprocess.Popen(
            [sys.executable, "-m", "shortener", service],
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
        processes.append(process)
        return process

    context = ssl.create_default_context(cafile=str(cert))

    def wait_http(base, process):
        deadline = time.monotonic() + 15
        with httpx.Client(verify=context, timeout=0.5, trust_env=False) as client:
            while time.monotonic() < deadline:
                assert process.poll() is None, "El servidor terminó inesperadamente"
                try:
                    if client.get(base + "/health").status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)
        raise AssertionError(f"El servicio no inició: {base}")

    try:
        start("log")
        credentials = grpc.ssl_channel_credentials(cert.read_bytes())
        with grpc.secure_channel(f"localhost:{log_port}", credentials) as channel:
            grpc.channel_ready_future(channel).result(timeout=10)
        v1 = start("v1", v1_port)
        v2 = start("v2", v2_port)
        base1, base2 = f"https://localhost:{v1_port}", f"https://localhost:{v2_port}"
        wait_http(base1, v1)
        wait_http(base2, v2)
        result = verify_services(base1, base2, cert)
        assert result["v1"]["grpc_logged_delta"] == 2
        assert result["v2"]["rate_limit_status"] == 429
        with connection(tmp_path / "log.db") as conn:
            assert conn.execute("SELECT COUNT(*) FROM hits").fetchone()[0] == 2
        # El certificado es realmente autofirmado: sin confiar en él falla TLS.
        with pytest.raises(httpx.ConnectError):
            httpx.get(base1 + "/health", timeout=2, trust_env=False)

        v2.terminate()
        v2.wait(timeout=5)
        v2 = start("v2", v2_port)
        wait_http(base2, v2)
        with httpx.Client(verify=context, follow_redirects=False, trust_env=False) as client:
            assert client.get(base2 + "/eRgfR").status_code == 301
            new = client.post(base2 + "/urls", json={"url": "https://usm.cl/postgrado"})
            assert new.json()["id"] == 597652314
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for handle in handles:
            handle.close()
