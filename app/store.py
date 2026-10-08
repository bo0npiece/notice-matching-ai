import json
import math
import re
import sqlite3
import time
import uuid
from collections import Counter
from pathlib import Path


class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS calls (
                    id TEXT PRIMARY KEY, created REAL, model TEXT,
                    prompt_tokens INTEGER, completion_tokens INTEGER, state TEXT
                );
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY, created REAL, value TEXT
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, title TEXT, created REAL
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY, document_id TEXT, content TEXT
                );
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def usage(self):
        with self.connect() as db:
            row = db.execute("""SELECT COUNT(*), COALESCE(SUM(prompt_tokens),0),
                COALESCE(SUM(completion_tokens),0),
                COALESCE(SUM(CASE WHEN prompt_tokens IS NULL THEN 1 ELSE 0 END),0)
                FROM calls""").fetchone()
        return dict(live_call_attempts=row[0], prompt_tokens=row[1], completion_tokens=row[2],
                    total_tokens=row[1] + row[2], unknown_usage_calls=row[3])

    def begin_call(self, model):
        call_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO calls(id,created,model,state) VALUES(?,?,?,?)",
                       (call_id, time.time(), model, "pending"))
        return call_id

    def finish_call(self, call_id, usage, state):
        p, c = usage.get("promptTokens"), usage.get("completionTokens")
        if type(p) is not int or type(c) is not int or p < 0 or c < 0:
            p = c = None
        with self.connect() as db:
            db.execute("UPDATE calls SET prompt_tokens=?, completion_tokens=?, state=? WHERE id=?",
                       (p, c, state, call_id))

    def cache_get(self, key, ttl):
        with self.connect() as db:
            row = db.execute("SELECT created,value FROM cache WHERE key=?", (key,)).fetchone()
        return json.loads(row[1]) if row and time.time() - row[0] < ttl else None

    def cache_put(self, key, value):
        with self.connect() as db:
            db.execute("DELETE FROM cache WHERE created<?", (time.time() - 86400,))
            db.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?)", (key, time.time(), json.dumps(value, ensure_ascii=False)))

    def add_document(self, title, text):
        doc_id = str(uuid.uuid4())
        parts = [text[i:i + 1000] for i in range(0, len(text), 850)]
        with self.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            if count + len(parts) > 1000:
                raise ValueError("데모 문서 저장 한도(1000 조각)를 초과합니다. 기존 문서를 삭제하세요.")
            db.execute("INSERT INTO documents VALUES(?,?,?)", (doc_id, title, time.time()))
            db.executemany("INSERT INTO chunks VALUES(?,?,?)", [(f"{doc_id}:{i + 1}", doc_id, part) for i, part in enumerate(parts)])
        return {"id": doc_id, "title": title, "chunks": len(parts)}

    def documents(self):
        with self.connect() as db:
            rows = db.execute("SELECT id,title,created FROM documents ORDER BY created DESC").fetchall()
        return [dict(id=r[0], title=r[1], created=r[2]) for r in rows]

    def delete_document(self, doc_id):
        with self.connect() as db:
            db.execute("DELETE FROM chunks WHERE document_id=?", (doc_id,))
            return db.execute("DELETE FROM documents WHERE id=?", (doc_id,)).rowcount > 0

    @staticmethod
    def features(text):
        # 한국어 조사 차이를 일부 흡수하는 문자 2-gram 검색. 임베딩 API 비용 없음.
        terms = re.findall(r"[가-힣a-z0-9]+", text.lower())
        return Counter(g for term in terms for g in ([term] if len(term) < 2 else [term[i:i+2] for i in range(len(term)-1)]))

    def search(self, query, doc_ids, limit):
        with self.connect() as db:
            rows = db.execute("SELECT c.id,c.document_id,d.title,c.content FROM chunks c JOIN documents d ON d.id=c.document_id").fetchall()
        q = self.features(query)
        qnorm = math.sqrt(sum(v*v for v in q.values())) or 1
        ranked = []
        for cid, did, title, content in rows:
            if doc_ids and did not in doc_ids:
                continue
            features = self.features(content)
            dot = sum(v * features.get(k, 0) for k, v in q.items())
            if dot:
                score = dot / (qnorm * (math.sqrt(sum(v*v for v in features.values())) or 1))
                ranked.append(dict(id=cid, document_id=did, title=title, text=content, score=round(score, 4)))
        return sorted(ranked, key=lambda r: r["score"], reverse=True)[:limit]
