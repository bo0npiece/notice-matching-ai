"""응답 캐시: 같은 요청을 다시 보내면 저장된 결과를 돌려줘 크레딧 절약."""
import json
import sqlite3
import time
from pathlib import Path


class ResponseCache:
    def __init__(self, path: Path, ttl: int):
        self.path = Path(path)
        self.ttl = ttl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, created REAL, value TEXT)")

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    @property
    def enabled(self) -> bool:
        return self.ttl > 0

    def get(self, key: str):
        with self._connect() as db:
            row = db.execute("SELECT created, value FROM cache WHERE key=?", (key,)).fetchone()
        if row and time.time() - row[0] < self.ttl:
            return json.loads(row[1])
        return None

    def put(self, key: str, value):
        with self._connect() as db:
            db.execute("DELETE FROM cache WHERE created < ?", (time.time() - self.ttl,))
            db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)",
                       (key, time.time(), json.dumps(value, ensure_ascii=False)))
