"""사용자 저장소 (SQLite, data/app.sqlite3): 익명 사용자 프로필 + 관심 공고·서류 체크리스트."""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    profile TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS saved_notices (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    notice_id TEXT NOT NULL,
    checked TEXT NOT NULL DEFAULT '[]',
    saved_at TEXT NOT NULL,
    PRIMARY KEY (user_id, notice_id)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class UserStore:
    def __init__(self, path: Path):
        """DB 파일과 테이블을 준비."""
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    # ---------- 사용자 ----------

    def create(self, profile: dict | None = None) -> dict:
        """익명 사용자 생성. profile은 호출하는 쪽에서 정규화해서 넘김."""
        user_id = uuid.uuid4().hex
        now = _now()
        profile = profile or {}
        with self._connect() as db:
            db.execute("INSERT INTO users VALUES (?, ?, ?, ?)",
                       (user_id, json.dumps(profile, ensure_ascii=False), now, now))
        return self.get(user_id)

    def get(self, user_id: str) -> dict:
        """사용자 조회. 없으면 404."""
        with self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            count = db.execute("SELECT COUNT(*) FROM saved_notices WHERE user_id=?", (user_id,)).fetchone()[0]
        if row is None:
            raise HTTPException(404, "사용자를 찾을 수 없습니다. POST /users로 다시 만들어 주세요.")
        return {"user_id": row["id"], "profile": json.loads(row["profile"]), "saved_count": count,
                "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def update_profile(self, user_id: str, profile: dict) -> dict:
        """프로필 저장(전체 교체)."""
        self.get(user_id)
        with self._connect() as db:
            db.execute("UPDATE users SET profile=?, updated_at=? WHERE id=?",
                       (json.dumps(profile, ensure_ascii=False), _now(), user_id))
        return self.get(user_id)

    # ---------- 관심 공고 ----------

    def save_notice(self, user_id: str, notice_id: str):
        """관심 공고 저장. 이미 있으면 그대로 둠."""
        self.get(user_id)
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO saved_notices (user_id, notice_id, saved_at) VALUES (?, ?, ?)",
                       (user_id, notice_id, _now()))

    def remove_notice(self, user_id: str, notice_id: str):
        """관심 공고 삭제. 저장돼 있지 않으면 404."""
        with self._connect() as db:
            cur = db.execute("DELETE FROM saved_notices WHERE user_id=? AND notice_id=?", (user_id, notice_id))
        if cur.rowcount == 0:
            raise HTTPException(404, f"저장된 공고 {notice_id}가 없습니다.")

    def set_checked(self, user_id: str, notice_id: str, checked: list[str]):
        """서류 체크 상태 저장(체크된 서류 이름 목록 전체 교체)."""
        with self._connect() as db:
            cur = db.execute("UPDATE saved_notices SET checked=? WHERE user_id=? AND notice_id=?",
                             (json.dumps(checked, ensure_ascii=False), user_id, notice_id))
        if cur.rowcount == 0:
            raise HTTPException(404, f"저장된 공고 {notice_id}가 없습니다. 먼저 저장해 주세요.")

    def saved_rows(self, user_id: str) -> list[dict]:
        """저장한 공고 원본 행 목록."""
        self.get(user_id)
        with self._connect() as db:
            rows = db.execute("SELECT notice_id, checked, saved_at FROM saved_notices WHERE user_id=?",
                              (user_id,)).fetchall()
        return [{"notice_id": r["notice_id"], "checked": json.loads(r["checked"]), "saved_at": r["saved_at"]}
                for r in rows]
