"""Demostración contra servicios HTTPS reales; nunca visita el sitio de destino."""

import argparse
import json
import ssl
from pathlib import Path

import httpx


def verify_services(v1: str, v2: str, certificate: Path, check_rate_limit: bool = True) -> dict:
    results = {}
    context = ssl.create_default_context(cafile=str(certificate))
    with httpx.Client(verify=context, follow_redirects=False, timeout=5, trust_env=False) as client:
        for version, base, expected in [("v1", v1.rstrip("/"), 302), ("v2", v2.rstrip("/"), 301)]:
            assert client.get(base + "/health").status_code == 200
            before = client.get(base + "/stats").json()
            created = client.post(base + "/urls", json={"url": "https://usm.cl/"})
            assert created.status_code == 201, created.text
            code = created.json()["hash"]
            responses = [client.get(f"{base}/{code}") for _ in range(2)]
            assert all(response.status_code == expected for response in responses)
            assert all(response.headers["location"] == "https://usm.cl/" for response in responses)
            after = client.get(base + "/stats").json()
            results[version] = {
                "create_status": created.status_code,
                "redirect_status": responses[-1].status_code,
                "location": responses[-1].headers["location"],
                "cache_control": responses[-1].headers["cache-control"],
                "database_lookups_delta": after["db_lookups"] - before["db_lookups"],
                "tls_verified": True,
            }
            if version == "v1":
                assert "no-store" in responses[-1].headers["cache-control"]
                results[version]["grpc_logged_delta"] = after["grpc_logged"] - before["grpc_logged"]
                assert results[version]["grpc_logged_delta"] == 2, (
                    "Comprueba que el servicio Log esté disponible"
                )
            else:
                results[version]["cache_hits_delta"] = after["cache_hits"] - before["cache_hits"]
                assert results[version]["database_lookups_delta"] == 1
                assert results[version]["cache_hits_delta"] == 1
                if check_rate_limit:
                    remaining = int(responses[-1].headers["ratelimit-remaining"])
                    assert remaining <= 1000, "Límite demasiado alto para esta demostración"
                    for _ in range(remaining):
                        assert client.get(f"{base}/{code}").status_code == 301
                    blocked = client.get(f"{base}/{code}")
                    assert blocked.status_code == 429
                    results[version]["rate_limit_status"] = blocked.status_code
                    results[version]["rate_limit_remaining"] = blocked.headers[
                        "ratelimit-remaining"
                    ]
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1", default="https://localhost:8443")
    parser.add_argument("--v2", default="https://localhost:8444")
    parser.add_argument("--cert", type=Path, default=Path("certs/server.crt"))
    parser.add_argument("--skip-rate-limit", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        results = verify_services(args.v1, args.v2, args.cert, not args.skip_rate_limit)
    except (httpx.HTTPError, AssertionError, OSError) as exc:
        parser.exit(
            1,
            f"Verificación fallida: {exc}. Revisa servicios y cuota; espera 60 s si ya probaste el límite.\n",
        )
    output = json.dumps(results, ensure_ascii=False, indent=2)
    print(output)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
