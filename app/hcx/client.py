"""HyperCLOVA X 호출 창구. 모든 HCX 호출은 이 파일만 거친다.

엔드포인트·파라미터 이름이 바뀌면 이 파일 위쪽 상수만 고치면 됨.
"""
import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from jsonschema import Draft202012Validator, ValidationError

from ..config import Settings
from .cache import ResponseCache
from .image import as_data_uri
from .mock import MOCK_CHAT_TEXT, MOCK_IMAGE_TEXT, fake_embedding, fake_from_schema
from .schema import clean_schema
from .usage import UsageLog

CHAT_PATH = "/v3/chat-completions/{model}"
EMBED_PATH = "/v1/api-tools/embedding/v2"
EMBED_MODEL = "embedding-v2"            # 로그 표시용 이름
RERANK_PATH = None                      # TODO: 경로 확인 (리랭커 API 문서 확인 전까지 실제 호출 안 함)
RAG_REASONING_PATH = None               # TODO: 경로 확인 (RAG Reasoning API 문서 확인 전까지 실제 호출 안 함)
COMPLETION_TOKEN_MODELS = ("HCX-007",)  # maxCompletionTokens를 쓰는 모델 (나머지는 maxTokens)
RETRY_DELAYS = (1.0, 3.0)               # 429일 때 기다렸다 재시도하는 간격(초)


class HCXError(Exception):
    """HCX 호출 실패. status_code는 우리 API가 돌려줄 HTTP 코드."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass
class HCXResult:
    text: str              # 모델이 쓴 원문 (embed는 빈 문자열)
    model: str
    usage: dict            # promptTokens / completionTokens / totalTokens
    mock: bool = False
    cached: bool = False
    latency_ms: int = 0
    data: Any = None       # chat_json: 파싱된 dict, embed: 벡터


def text_message(role: str, text: str) -> dict:
    """{"role", "content": [{"type": "text", ...}]} 형식 메시지 만들기."""
    return {"role": role, "content": [{"type": "text", "text": text}]}


def _normalize(messages: list[dict]) -> list[dict]:
    # content가 문자열이면 v3 배열 형식으로 변환
    return [text_message(m["role"], m["content"]) if isinstance(m["content"], str) else m
            for m in messages]


def _content_text(content) -> str:
    # 응답 content가 문자열이 아니라 배열로 올 경우 대비
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    raise HCXError(502, "HCX 응답 형식이 예상과 다릅니다.")


def _token_key(model: str) -> str:
    return "maxCompletionTokens" if model.startswith(COMPLETION_TOKEN_MODELS) else "maxTokens"


class HCXClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport  # 테스트에서 가짜 서버를 끼울 때 사용
        self.usage = UsageLog(settings.usage_log_path)
        self.cache = ResponseCache(settings.data_dir / "hcx_cache.sqlite3", settings.cache_ttl)
        self.retry_delays = RETRY_DELAYS

    # ---------- 공개 함수 ----------

    async def chat(self, feature: str, messages: list[dict], *, model: str | None = None,
                   max_tokens: int = 1024, temperature: float = 0.5, use_cache: bool = True) -> HCXResult:
        """일반 대화. 기본 모델은 가벼운 HCX-DASH-002."""
        model = model or self.settings.model_light
        if self.settings.mock:
            return self._mock(feature, "chat", model, text=MOCK_CHAT_TEXT.format(feature=feature))
        payload = {"messages": _normalize(messages), _token_key(model): max_tokens,
                   "temperature": temperature, "topP": 0.8}
        result, latency, cached = await self._post(feature, "chat", CHAT_PATH.format(model=model), payload, model, use_cache)
        text = _content_text(result["message"]["content"])
        return HCXResult(text, model, result.get("usage") or {}, cached=cached, latency_ms=latency)

    async def chat_json(self, feature: str, system: str, user: str, schema: dict, *,
                        max_tokens: int = 2048, temperature: float = 0, use_cache: bool = True,
                        mock_sample: str | None = None) -> HCXResult:
        """Structured Outputs(HCX-007 전용). system 메시지는 1개만 허용되므로 문자열로 받음.
        MOCK에서는 customize/samples/{mock_sample 또는 feature}.json 이 있으면 그 값을 돌려줌."""
        model = self.settings.model_analysis
        sent_schema = clean_schema(schema)
        if self.settings.mock:
            data = self._sample(mock_sample or feature)
            if data is None:
                data = fake_from_schema(sent_schema)
            return self._mock(feature, "json", model, text=json.dumps(data, ensure_ascii=False), data=data)
        payload = {
            "messages": [text_message("system", system), text_message("user", user)],
            _token_key(model): max_tokens,
            "temperature": temperature,
            "thinking": {"effort": "none"},  # Structured Outputs 필수 조건
            "responseFormat": {"type": "json", "schema": sent_schema},
        }
        result, latency, cached = await self._post(feature, "json", CHAT_PATH.format(model=model), payload, model, use_cache)
        if result.get("finishReason") == "length":
            raise HCXError(502, "JSON 출력이 토큰 한도에서 잘렸습니다. max_tokens를 늘려 주세요.")
        text = _content_text(result["message"]["content"])
        try:
            data = json.loads(text)
            Draft202012Validator(sent_schema).validate(data)  # 안전망 검사
        except (ValueError, ValidationError):
            raise HCXError(502, "AI 결과가 지정한 JSON 형식과 다릅니다.") from None
        return HCXResult(text, model, result.get("usage") or {}, cached=cached, latency_ms=latency, data=data)

    async def read_image(self, feature: str, prompt: str, *, image_b64: str | None = None,
                         image_url: str | None = None, max_tokens: int = 1024, use_cache: bool = True,
                         mock_sample: str | None = None) -> HCXResult:
        """이미지 읽기(HCX-005). image_b64는 image.prepare_image() 결과(data URI)를 넣음.
        MOCK에서는 customize/samples/{mock_sample 또는 feature}.txt 가 있으면 그 글을 돌려줌."""
        if not (image_b64 or image_url):
            raise ValueError("image_b64 또는 image_url 중 하나는 필요합니다.")
        model = self.settings.model_vision
        if self.settings.mock:
            path = self.settings.customize_dir / "samples" / f"{mock_sample or feature}.txt"
            text = path.read_text(encoding="utf-8-sig") if path.is_file() else MOCK_IMAGE_TEXT
            return self._mock(feature, "image", model, text=text)
        image_part = ({"type": "image_url", "dataUri": {"data": as_data_uri(image_b64)}} if image_b64
                      else {"type": "image_url", "imageUrl": {"url": image_url}})
        payload = {
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, image_part]}],
            _token_key(model): max_tokens,
            "temperature": 0,
        }
        result, latency, cached = await self._post(feature, "image", CHAT_PATH.format(model=model), payload, model, use_cache)
        text = _content_text(result["message"]["content"])
        return HCXResult(text, model, result.get("usage") or {}, cached=cached, latency_ms=latency)

    async def embed(self, feature: str, text: str, *, use_cache: bool = True) -> HCXResult:
        """임베딩 v2 (1024차원)."""
        if self.settings.mock:
            return self._mock(feature, "embed", EMBED_MODEL, data=fake_embedding(text))
        result, latency, cached = await self._post(feature, "embed", EMBED_PATH, {"text": text}, EMBED_MODEL, use_cache)
        vector = result.get("embedding")
        if not isinstance(vector, list):
            raise HCXError(502, "임베딩 응답 형식이 예상과 다릅니다.")
        return HCXResult("", EMBED_MODEL, result.get("usage") or {}, cached=cached, latency_ms=latency, data=vector)

    async def rerank(self, feature: str, query: str, documents: list[str]) -> HCXResult:
        """리랭커. data = 문서별 점수 리스트(documents 순서 그대로).
        MOCK에서는 fake_embedding 코사인으로 점수를 만듦."""
        if self.settings.mock:
            q = fake_embedding(query)
            scores = [sum(a * b for a, b in zip(q, fake_embedding(d))) for d in documents]
            return self._mock(feature, "rerank", "reranker", data=scores)
        if RERANK_PATH is None:
            # TODO: 경로 확인 — 리랭커 요청/응답 형식 확인 후 구현
            raise HCXError(501, "리랭커 API 경로가 아직 설정되지 않았습니다.")
        raise HCXError(501, "리랭커 호출은 아직 구현되지 않았습니다.")

    async def rag_reasoning(self, feature: str, query: str, documents: list[dict], *,
                            mock_sample: str | None = None) -> HCXResult:
        """RAG Reasoning. documents = [{"id","text"}]. MOCK에서는 samples 응답을 돌려줌."""
        if self.settings.mock:
            data = self._sample(mock_sample or feature)
            return self._mock(feature, "rag", "rag-reasoning", text=json.dumps(data, ensure_ascii=False), data=data)
        if RAG_REASONING_PATH is None:
            # TODO: 경로 확인 — RAG Reasoning 요청/응답 형식 확인 후 구현
            raise HCXError(501, "RAG Reasoning API 경로가 아직 설정되지 않았습니다.")
        raise HCXError(501, "RAG Reasoning 호출은 아직 구현되지 않았습니다.")

    # ---------- 내부 함수 ----------

    def _sample(self, name: str):
        """customize/samples/{name}.json 읽기. 없으면 None."""
        path = self.settings.customize_dir / "samples" / f"{name}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def _mock(self, feature, kind, model, text="", data=None) -> HCXResult:
        self.usage.append(feature=feature, kind=kind, model=model, mock=True, cached=False, status="ok")
        return HCXResult(text, model, {}, mock=True, data=data)

    def _check_budget(self):
        totals = self.usage.live_totals()
        if totals["live_calls"] >= self.settings.max_live_calls:
            raise HCXError(429, "실제 API 호출 횟수 한도(MAX_LIVE_CALLS)에 도달했습니다.")
        if totals["total_tokens"] >= self.settings.token_stop_threshold:
            raise HCXError(429, "누적 토큰 중단 기준(TOKEN_STOP_THRESHOLD)에 도달했습니다.")

    async def _post(self, feature, kind, path, payload, model, use_cache):
        """실제 POST. (result, latency_ms, cached) 반환."""
        cacheable = use_cache and self.cache.enabled and payload.get("temperature", 0) == 0
        key = hashlib.sha256(json.dumps([self.settings.base_url, path, payload],
                                        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if cacheable and (saved := self.cache.get(key)) is not None:
            self.usage.append(feature=feature, kind=kind, model=model, mock=False, cached=True, status="ok")
            return saved, 0, True

        self._check_budget()
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "X-NCP-CLOVASTUDIO-REQUEST-ID": str(uuid.uuid4()),
            "Content-Type": "application/json",
        }
        log = dict(feature=feature, kind=kind, model=model, mock=False, cached=False)

        async with httpx.AsyncClient(base_url=self.settings.base_url, timeout=self.settings.timeout,
                                     transport=self.transport) as client:
            for attempt in range(len(self.retry_delays) + 1):
                started = time.perf_counter()
                try:
                    response = await client.post(path, headers=headers, json=payload)
                except httpx.TimeoutException:
                    self.usage.append(**log, status="error", latency_ms=_ms(started), error="timeout")
                    raise HCXError(504, "HCX 응답 시간 초과") from None
                except httpx.RequestError:
                    self.usage.append(**log, status="error", latency_ms=_ms(started), error="connect")
                    raise HCXError(502, "HCX 연결 실패: 네트워크와 CLOVA_BASE_URL을 확인하세요.") from None
                latency = _ms(started)
                if response.status_code == 429 and attempt < len(self.retry_delays):
                    # 레이트리밋: 잠깐 쉬었다가 재시도
                    self.usage.append(**log, status="error", latency_ms=latency, error="429 retry")
                    await asyncio.sleep(self.retry_delays[attempt])
                    continue
                break

        if response.status_code != 200:
            detail = _error_detail(response)
            self.usage.append(**log, status="error", latency_ms=latency, error=f"HTTP {response.status_code}")
            hint = {401: "API 키 확인", 403: "모델 사용 권한 확인", 429: "호출 제한, 잠시 후 다시 시도"}.get(response.status_code, "요청 확인")
            raise HCXError(502, f"HCX HTTP {response.status_code} ({hint}) {detail}".strip())

        try:
            body = response.json()
            code = str(body["status"]["code"])
            result = body["result"]
        except (ValueError, KeyError, TypeError):
            self.usage.append(**log, status="error", latency_ms=latency, error="bad response")
            raise HCXError(502, "HCX 응답 형식이 예상과 다릅니다.") from None
        if code != "20000":
            self.usage.append(**log, status="error", latency_ms=latency, error=f"code {code}")
            raise HCXError(502, f"HCX 오류 코드 {code}: {body['status'].get('message', '')}")

        self.usage.append(**log, status="ok", usage=_usage_of(result), latency_ms=latency)
        if cacheable:
            self.cache.put(key, result)
        return result, latency, False


def _usage_of(result: dict) -> dict | None:
    """응답의 토큰 사용량. 임베딩 v2는 usage 대신 inputTokens만 줌."""
    if isinstance(result.get("usage"), dict):
        return result["usage"]
    if isinstance(result.get("inputTokens"), int):
        n = result["inputTokens"]
        return {"promptTokens": n, "completionTokens": 0, "totalTokens": n}
    return None


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _error_detail(response: httpx.Response) -> str:
    # 오류 원인 파악용으로 status.message만 짧게 꺼냄
    try:
        status = response.json().get("status") or {}
        return str(status.get("message", ""))[:300]
    except (ValueError, AttributeError):
        return response.text[:300]
