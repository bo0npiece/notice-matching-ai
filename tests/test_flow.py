"""2~4단계: /explain, /ask, /notice/upload, /usage (MOCK + 가짜 HCX 서버)."""
import io
import json

import httpx
from PIL import Image

from app.hcx.mock import fake_embedding

from .conftest import build_client, hcx_reply

PROFILE = {"age": 22, "region": "경기", "city": "용인", "school_year": 3,
           "major": "인공지능", "enrolled": True, "living_alone": True}


def png_bytes():
    out = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(out, format="PNG")
    return out.getvalue()


# ---------- MOCK ----------

def test_explain_mock(client):
    body = client.post("/explain", json={"profile": PROFILE, "notice_id": "n003"}).json()
    conds = body["conditions"]
    assert body["dday"] is not None and body["documents"]
    assert all(c["status"] in ("pass", "fail", "unknown") for c in conds)   # ai는 모두 판단됨
    assert all(c["reason"] and c["source"] for c in conds)
    assert {c["by"] for c in conds} == {"rule", "ai"}


def test_explain_404(client):
    r = client.post("/explain", json={"profile": PROFILE, "notice_id": "n999"})
    assert r.status_code == 404 and "error" in r.json()


def test_ask_mock(client):
    body = client.post("/ask", json={"question": "국가장학금이랑 중복 돼?", "notice_id": "n001"}).json()
    assert body["answer"] and body["sources"][0]["notice_id"] == "n001"
    body = client.post("/ask", json={"question": "월세 지원 금액은?"}).json()
    assert body["answer"] and isinstance(body["sources"], list)


def test_upload_mock(client):
    r = client.post("/notice/upload", files={"file": ("poster.png", png_bytes(), "image/png")})
    notice = r.json()["notice"]
    assert r.status_code == 200 and notice["id"] == "n006"
    assert "emb" not in notice["chunks"][0]
    ids = [i["id"] for i in client.post("/recommend", json={"profile": PROFILE, "top_k": 10}).json()["items"]]
    assert "n006" in ids    # 업로드 즉시 추천에 반영


def test_upload_bad_image(client):
    r = client.post("/notice/upload", files={"file": ("x.png", b"not image", "image/png")})
    assert r.status_code == 400 and "error" in r.json()


def test_usage(client):
    client.post("/profile", json={"text": "22살"})
    body = client.get("/usage").json()
    assert {"total_tokens", "by_call", "logs"} <= set(body)
    assert body["logs"][0]["feature"] == "profile_parse"


# ---------- 실제 모드 (가짜 HCX 서버) ----------

def fake_hcx(path_log):
    """임베딩·chat을 흉내 내는 가짜 HCX 서버."""
    def handler(request: httpx.Request):
        path_log.append(request.url.path)
        payload = json.loads(request.content)
        if request.url.path.endswith("/embedding/v2"):
            return httpx.Response(200, json={"status": {"code": "20000"},
                                             "result": {"embedding": fake_embedding(payload["text"]), "inputTokens": 7}})
        assert payload["thinking"] == {"effort": "none"}
        assert 0.1 <= payload["temperature"] <= 0.3
        if "판단할 조건" in payload["messages"][0]["content"][0]["text"]:
            return hcx_reply({"results": [{"index": 0, "status": "unknown", "reason": "소득 확인 필요"}]}, 30)
        return hcx_reply({"answer": "공고에 명시되지 않았습니다.", "used": []}, 20)
    return handler


def test_real_explain_falls_back_to_hcx007(tmp_path):
    calls = []
    client = build_client(tmp_path, handler=fake_hcx(calls))
    body = client.post("/explain", json={"profile": PROFILE, "notice_id": "n002"}).json()
    assert body["conditions"][-1]["reason"] == "소득 확인 필요"
    assert calls == ["/v3/chat-completions/HCX-007"]
    # 같은 프로필·공고는 메모리 캐시 → 재호출 없음
    client.post("/explain", json={"profile": PROFILE, "notice_id": "n002"})
    assert len(calls) == 1


def test_real_usage_records_tokens(tmp_path):
    client = build_client(tmp_path, handler=fake_hcx([]))
    assert client.post("/ask", json={"question": "중복 지원 돼?"}).json()["answer"] == "공고에 명시되지 않았습니다."
    body = client.get("/usage").json()
    by = {c["feature"]: c for c in body["by_call"]}
    assert by["ask_search"]["total_tokens"] == 7     # 임베딩 inputTokens 기록
    assert by["ask"]["total_tokens"] == 20
    assert body["total_tokens"] == 27


def test_real_hcx_error_is_json(tmp_path):
    client = build_client(tmp_path, handler=lambda r: httpx.Response(401, json={"status": {"code": "40100", "message": "bad key"}}))
    r = client.post("/profile", json={"text": "22살"})
    assert r.status_code == 502 and "401" in r.json()["error"]
