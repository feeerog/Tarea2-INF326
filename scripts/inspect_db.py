"""Inspección local reproducible; no requiere instalar sqlite3 como comando."""

import argparse
import json
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--table", choices=["urls", "hits"], default="urls")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error(f"No existe {args.database}; primero inicia el servicio")
    conn = sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        # table procede exclusivamente de la lista cerrada de argparse.
        rows = conn.execute(
            f"SELECT * FROM {args.table} ORDER BY id DESC LIMIT ?", (max(1, args.limit),)
        ).fetchall()
        print(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
