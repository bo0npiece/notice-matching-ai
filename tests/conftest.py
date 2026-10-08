"""공통 테스트 도구."""
import json
import shutil
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]


def build_client(tmp_path, handler=None, **env):
    """customize 사본 + MOCK 인덱스 사본을 쓰는 임시 앱.
    handler를 주면 실제 모드로 켜고 HCX 대신 가짜 서버(httpx.MockTransport)를 붙임."""
    if not (tmp_path / "customize").exists():
        shutil.copytree(ROOT / "customize", tmp_path / "customize")
        (tmp_path / "data").mkdir()
        mock_index = ROOT / "data" / "notices.mock.json"
        shutil.copy(mock_index, tmp_path / "data" / "notices.mock.json")
        shutil.copy(mock_index, tmp_path / "data" / "notices.json")  # 실제 모드 테스트용
    env = {"MOCK_MODE": "1", "DATA_DIR": str(tmp_path / "data"), "CUSTOMIZE_DIR": str(tmp_path / "customize"),
           "CACHE_TTL_SECONDS": "0", **env}
    if handler:
        env["MOCK_MODE"] = "0"
        env.setdefault("CLOVA_API_KEY", "test-key")
    app = create_app(Settings.from_env(env))
    if handler:
        app.state.core.hcx.transport = httpx.MockTransport(handler)
    return TestClient(app)


def hcx_reply(content, total_tokens=10):
    """가짜 HCX chat 성공 응답."""
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    return httpx.Response(200, json={
        "status": {"code": "20000"},
        "result": {"message": {"role": "assistant", "content": content}, "finishReason": "stop",
                   "usage": {"promptTokens": total_tokens - 1, "completionTokens": 1, "totalTokens": total_tokens}},
    })


@pytest.fixture
def client(tmp_path):
    return build_client(tmp_path)
