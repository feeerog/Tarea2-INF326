"""SQLite persistente, conexiones por operación y asignación atómica de IDs."""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from shortener.common.base62 import INITIAL_ID, encode


@contextmanager
def connection(path: Path):
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        # Cerrar también revierte cualquier transacción que no llegó a COMMIT.
        conn.close()


@dataclass(frozen=True)
class UrlRecord:
    id: int
    hash: str
    long_url: str


class UrlRepository:
    def __init__(self, path: Path):
        self.path = path
        self.lookup_count = 0
        self._metrics_lock = Lock()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with connection(self.path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS urls ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "hash TEXT NOT NULL UNIQUE, long_url TEXT NOT NULL)"
            )
            # Se hace una sola vez; un reinicio jamás reinicia la secuencia.
            if conn.execute("SELECT 1 FROM sqlite_sequence WHERE name='urls'").fetchone() is None:
                conn.execute(
                    "INSERT INTO sqlite_sequence(name, seq) VALUES ('urls', ?)",
                    (INITIAL_ID - 1,),
                )
            conn.commit()

    def create(self, long_url: str) -> UrlRecord:
        with connection(self.path) as conn:
            # Reserva exclusiva del escritor: leer secuencia + insertar es atómico.
            # No se usa MAX(id)+1 ni un contador en memoria.
            conn.execute("BEGIN IMMEDIATE")
            identifier = conn.execute(
                "SELECT seq + 1 FROM sqlite_sequence WHERE name='urls'"
            ).fetchone()[0]
            record = UrlRecord(identifier, encode(identifier), long_url)
            conn.execute(
                "INSERT INTO urls(id, hash, long_url) VALUES (?, ?, ?)",
                (record.id, record.hash, record.long_url),
            )
            # SQLite actualiza sqlite_sequence al insertar el ID explícito.
            conn.commit()
        return record

    def get(self, code: str) -> UrlRecord | None:
        with self._metrics_lock:
            self.lookup_count += 1
        with connection(self.path) as conn:
            row = conn.execute(
                "SELECT id, hash, long_url FROM urls WHERE hash=?", (code,)
            ).fetchone()
        return UrlRecord(**dict(row)) if row else None

    def check(self) -> None:
        with connection(self.path) as conn:
            conn.execute("SELECT 1 FROM urls LIMIT 1").fetchone()
