"""MOCK 모드용 가짜 응답. 실제 API를 부르지 않고 프론트 개발을 할 수 있게 함."""
import hashlib
import math

EMBED_DIM = 1024

# TODO(DAY-OF): 데모 시나리오에 맞는 예시 문구로 교체 가능
MOCK_CHAT_TEXT = "[MOCK] {feature} 응답 예시입니다."
MOCK_IMAGE_TEXT = "[MOCK] 캡처에서 읽은 텍스트 예시입니다."


def fake_from_schema(schema: dict, name: str = "value"):
    """JSON 스키마를 보고 그럴듯한 값을 채움."""
    if "anyOf" in schema:
        return fake_from_schema(schema["anyOf"][0], name)
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type", "string")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "null")

    if kind == "object":
        return {key: fake_from_schema(sub, key) for key, sub in schema.get("properties", {}).items()}
    if kind == "array":
        count = max(schema.get("minItems", 0), 1)
        count = min(count, schema.get("maxItems", count))
        return [fake_from_schema(schema.get("items", {}), name) for _ in range(count)]
    if kind in ("integer", "number"):
        low, high = schema.get("minimum", 0), schema.get("maximum", 100)
        mid = low + (high - low) * 0.7  # 점수 게이지가 보기 좋게 70% 지점
        return round(mid) if kind == "integer" else round(mid, 2)
    if kind == "boolean":
        return True
    if kind == "null":
        return None
    return f"[MOCK] {name}"


def fake_embedding(text: str) -> list[float]:
    """글자 2-gram 해시 벡터. 비슷한 글끼리 유사도가 높게 나와 MOCK에서도 RAG 흐름 확인 가능."""
    vec = [0.0] * EMBED_DIM
    grams = [text[i:i + 2] for i in range(max(len(text) - 1, 1))]
    for gram in grams:
        index = int(hashlib.md5(gram.encode()).hexdigest(), 16) % EMBED_DIM
        vec[index] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]
