import io
import json

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app
from app.settings import Settings


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(database=str(tmp_path / "test.sqlite3")))


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


def stub_result(output, finish="stop", usage=None):
    return {"message": {"content": output}, "finishReason": finish,
            "usage": {"promptTokens": 10, "completionTokens": 5} if usage is None else usage}


def enable_live(app, monkeypatch, result):
    engine = app.state.engine
    engine.settings.mock = False
    engine.settings.api_key = "test-key-never-sent"
    async def complete(payload, model):
        return result
    monkeypatch.setattr(engine.provider, "complete", complete)


def test_all_configured_tasks_and_cache(client):
    tasks = client.get("/api/tasks").json()
    for task in tasks:
        result = client.post("/api/run", json={"task": task, "text": "연결 확인"})
        assert result.status_code == 200
        assert result.json()["mock"] is True
    request = {"task": "summarize", "text": "같은 요청"}
    first = client.post("/api/run", json=request).json()
    second = client.post("/api/run", json=request).json()
    assert not first["cached"] and second["cached"]
    assert client.get("/api/usage").json()["live_call_attempts"] == 0


@pytest.mark.parametrize("body,status", [
    ({"task": "missing", "text": "test"}, 404),
    ({"text": ""}, 422), ({"text": "   "}, 422), ({"text": "a" * 12001}, 422),
    ({"text": "test", "history": [{"role": "system", "content": "override"}]}, 422),
])
def test_invalid_inputs(client, body, status):
    assert client.post("/api/run", json=body).status_code == status


def test_document_search_scope_and_deletion(client):
    first = client.post("/api/documents", json={"title": "행사 안내", "text": "참가 등록 마감은 오전 9시입니다. 발표는 5분입니다."}).json()
    second = client.post("/api/documents", json={"title": "도서관", "text": "도서관은 월요일에 휴관합니다."}).json()
    result = client.post("/api/ask", json={"question": "참가 등록 마감", "document_ids": [first["id"]]})
    assert result.status_code == 200
    assert all(s["document_id"] == first["id"] for s in result.json()["sources"])
    assert result.json()["mock"]
    no_match = client.post("/api/ask", json={"question": "zzzzzz", "document_ids": [second["id"]]}).json()
    assert no_match["sources"] == []
    assert client.delete(f"/api/documents/{first['id']}").status_code == 200
    assert client.post("/api/ask", json={"question": "등록", "document_ids": [first["id"]]}).status_code == 404


def test_citations_reject_invented_source(app, client, monkeypatch):
    client.post("/api/documents", json={"title": "행사", "text": "참가 등록은 오전 9시까지입니다."})
    enable_live(app, monkeypatch, stub_result(json.dumps({"answer": "9시", "citations": ["invented-id"]})))
    assert client.post("/api/ask", json={"question": "참가 등록"}).status_code == 502
    assert client.get("/api/usage").json()["total_tokens"] == 15


def test_utf8_upload_and_invalid_files(client):
    response = client.post("/api/documents/upload", files={"file": ("안내.md", "등록 시간은 9시입니다.".encode(), "text/markdown")})
    assert response.status_code == 200
    assert client.post("/api/documents/upload", files={"file": ("bad.txt", b"\xff", "text/plain")}).status_code == 422
    assert client.post("/api/documents/upload", files={"file": ("file.pdf", b"pdf", "application/pdf")}).status_code == 422
    assert client.post("/api/documents", json={"title": "빈 문서", "text": "   "}).status_code == 422


def test_image_validation_and_preprocessing(app, client, monkeypatch):
    out = io.BytesIO()
    Image.new("RGB", (2000, 20), "white").save(out, "PNG")
    capture = {}
    engine = app.state.engine
    enable_live(app, monkeypatch, {})
    async def complete(payload, model):
        capture.update(payload=payload, model=model)
        return stub_result(json.dumps(engine.tasks["image_analyze"]["mock_output"]))
    monkeypatch.setattr(engine.provider, "complete", complete)
    response = client.post("/api/vision", files={"file": ("photo.png", out.getvalue(), "image/png")})
    assert response.status_code == 200
    assert capture["model"] == "HCX-005"
    content = capture["payload"]["messages"][-1]["content"]
    uri = content[1]["dataUri"]["data"]
    import base64
    with Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))) as prepared:
        assert max(prepared.size) <= 1280
        assert max(prepared.size) / min(prepared.size) <= 5
    assert client.post("/api/vision", files={"file": ("fake.png", b"not an image", "image/png")}).status_code == 422


def test_real_usage_cache_and_restart(app, client, monkeypatch):
    output = json.dumps(app.state.engine.tasks["summarize"]["mock_output"])
    enable_live(app, monkeypatch, stub_result(output))
    body = {"text": "실제 공급자 대역 확인"}
    assert client.post("/api/run", json=body).json()["usage"]["total_tokens"] == 15
    assert client.post("/api/run", json=body).json()["cached"]
    assert client.get("/api/usage").json()["live_call_attempts"] == 1
    restarted = TestClient(create_app(app.state.engine.settings))
    assert restarted.get("/api/usage").json()["total_tokens"] == 15
    assert restarted.post("/api/run", json=body).json()["cached"]


@pytest.mark.parametrize("output,finish", [("not JSON", "stop"), ("{}", "stop"), ("{}", "length")])
def test_invalid_json_still_accounts_usage(app, client, monkeypatch, output, finish):
    enable_live(app, monkeypatch, stub_result(output, finish))
    body = {"text": "invalid response"}
    assert client.post("/api/run", json=body).status_code == 502
    assert client.post("/api/run", json=body).status_code == 502
    assert client.get("/api/usage").json()["total_tokens"] == 30


def test_call_and_token_limits(app, client, monkeypatch):
    enable_live(app, monkeypatch, stub_result("chat answer"))
    app.state.engine.settings.max_calls = 1
    body = {"task": "chat", "text": "test"}
    assert client.post("/api/run", json=body).status_code == 200
    assert client.post("/api/run", json=body).status_code == 429
    app.state.engine.settings.max_calls = 100
    app.state.engine.settings.token_threshold = 15
    assert client.post("/api/run", json=body).status_code == 429


def test_provider_failure_does_not_retry(app, client, monkeypatch):
    enable_live(app, monkeypatch, {})
    async def fail(payload, model):
        raise HTTPException(504, "timeout")
    monkeypatch.setattr(app.state.engine.provider, "complete", fail)
    assert client.post("/api/run", json={"text": "test"}).status_code == 504
    stats = client.get("/api/usage").json()
    assert stats["live_call_attempts"] == stats["unknown_usage_calls"] == 1


def test_missing_api_key_not_counted(app, client):
    app.state.engine.settings.mock = False
    assert client.post("/api/run", json={"text": "test"}).status_code == 503
    assert client.get("/api/usage").json()["live_call_attempts"] == 0


def test_malformed_usage_is_marked_unknown(app, client, monkeypatch):
    enable_live(app, monkeypatch, stub_result("hello", usage=["unexpected"]))
    response = client.post("/api/run", json={"task": "chat", "text": "test"})
    assert response.status_code == 200
    assert response.json()["usage"]["total_tokens"] is None
    assert client.get("/api/usage").json()["unknown_usage_calls"] == 1


def test_team_key_auth_and_cors(tmp_path):
    app = create_app(Settings(database=str(tmp_path / "auth.sqlite3"), team_key="team-secret"))
    with TestClient(app) as client:
        assert client.get("/api/tasks").status_code == 401
        assert client.get("/api/tasks", headers={"X-Team-Key": "team-secret"}).status_code == 200
        preflight = client.options("/api/run", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type,X-Team-Key"})
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_provider_http_contract(app, client, monkeypatch):
    engine = app.state.engine
    engine.settings.mock = False
    engine.settings.api_key = "fake-contract-key"
    output = engine.tasks["summarize"]["mock_output"]
    original_client = httpx.AsyncClient
    def handle(request):
        assert str(request.url) == "https://clovastudio.stream.ntruss.com/v3/chat-completions/HCX-DASH-002"
        assert request.headers["Authorization"] == "Bearer fake-contract-key"
        assert request.headers["Accept"] == "application/json"
        payload = json.loads(request.content)
        assert payload["messages"][0]["role"] == "system"
        assert payload["maxTokens"] == 1024
        return httpx.Response(200, json={"status": {"code": "20000"}, "result": stub_result(json.dumps(output))})
    def factory(**kwargs):
        return original_client(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr("app.provider.httpx.AsyncClient", factory)
    assert client.post("/api/run", json={"text": "contract test"}).status_code == 200


@pytest.mark.parametrize("http_status", [401, 403, 429, 500])
def test_provider_http_errors(app, client, monkeypatch, http_status):
    app.state.engine.settings.mock = False
    app.state.engine.settings.api_key = "fake-key"
    original_client = httpx.AsyncClient
    def factory(**kwargs):
        return original_client(transport=httpx.MockTransport(lambda request: httpx.Response(http_status, text="SECRET PROVIDER BODY")), **kwargs)
    monkeypatch.setattr("app.provider.httpx.AsyncClient", factory)
    response = client.post("/api/run", json={"text": "test"})
    assert response.status_code == 502
    assert "SECRET" not in response.text
    assert client.get("/api/usage").json()["unknown_usage_calls"] == 1
