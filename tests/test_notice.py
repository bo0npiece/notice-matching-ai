"""1단계: /health, /notices, /profile, /recommend (MOCK)."""
from datetime import date

from app.services.judge_service import calc_dday, judge_rule, normalize_region

PROFILE = {"age": 22, "region": "경기도", "city": "용인시", "school_year": 3,
           "major": "인공지능", "enrolled": True, "interests": ["AI"]}


def test_health(client):
    body = client.get("/health").json()
    assert body["mock"] is True and body["notice_count"] == 5


def test_notices(client):
    items = client.get("/notices").json()["items"]
    assert {i["id"] for i in items} == {"n001", "n002", "n003", "n004", "n005"}


def test_profile_mock(client):
    profile = client.post("/profile", json={"text": "용인 사는 22살 AI학과 3학년"}).json()["profile"]
    assert profile["age"] == 22 and profile["school"] is None


def test_recommend_excludes_fail(client):
    items = client.post("/recommend", json={"profile": PROFILE, "top_k": 5}).json()["items"]
    ids = [i["id"] for i in items]
    assert "n004" not in ids            # 서울 거주 조건 → fail → 제외
    assert {"n001", "n002", "n003", "n005"} <= set(ids)
    assert all(0 <= i["score"] <= 1 for i in items)
    assert set(items[0]["status_count"]) == {"pass", "fail", "unknown", "ai"}


def test_error_format(client):
    r = client.post("/recommend", json={})
    assert r.status_code == 422 and "error" in r.json()


def test_judge_rule():
    assert normalize_region("경기도") == normalize_region("경기") == "경기"
    assert judge_rule({"key": "region", "type": "in", "values": ["용인"]}, {"region": "경기", "city": "용인시"}) == "pass"
    assert judge_rule({"key": "age", "type": "range", "min": 19, "max": 34}, {"age": 35}) == "fail"
    assert judge_rule({"key": "gpa", "type": "range", "min": 3.0}, {}) == "unknown"
    assert judge_rule({"key": "etc", "type": "text"}, {}) == "ai"


def test_dday():
    assert calc_dday("2026-10-31", date(2026, 10, 8)) == 23
    assert calc_dday(None) is None
