"""Base de datos exclusiva del componente Log."""

from pathlib import Path

from shortener.common.database import connection


class LogRepository:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with connection(self.path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS hits ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "event_id TEXT NOT NULL UNIQUE, timestamp TEXT NOT NULL, "
                "short_url TEXT NOT NULL, long_url TEXT NOT NULL, hash TEXT NOT NULL)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS hits_hash_timestamp ON hits(hash, timestamp)")

    def add(self, event_id: str, timestamp: str, short_url: str, long_url: str, code: str) -> bool:
        with connection(self.path) as conn:
            cursor = conn.execute(
                "INSERT INTO hits(event_id, timestamp, short_url, long_url, hash) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(event_id) DO NOTHING",
                (event_id, timestamp, short_url, long_url, code),
            )
            return cursor.rowcount == 1

    def check(self) -> None:
        with connection(self.path) as conn:
            conn.execute("SELECT 1 FROM hits LIMIT 1").fetchone()
