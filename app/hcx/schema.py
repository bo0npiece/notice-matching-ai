"""Structured Outputs 스키마 정리: HCX가 지원하는 키워드만 남김."""
import copy

# HCX-007 Structured Outputs 지원 키워드 (pattern 등은 미지원)
SUPPORTED_KEYS = {
    "type", "properties", "required", "items", "enum", "anyOf",
    "format", "minimum", "maximum", "minItems", "maxItems",
}


def clean_schema(schema: dict) -> dict:
    """지원 안 되는 키를 재귀적으로 제거한 사본을 반환."""
    if not isinstance(schema, dict):
        return copy.deepcopy(schema)
    out = {}
    for key, value in schema.items():
        if key not in SUPPORTED_KEYS:
            continue
        if key == "properties":
            # properties의 키는 필드 이름이므로 값만 정리
            out[key] = {name: clean_schema(sub) for name, sub in value.items()}
        elif key == "items":
            out[key] = clean_schema(value)
        elif key == "anyOf":
            out[key] = [clean_schema(sub) for sub in value]
        else:
            out[key] = copy.deepcopy(value)
    return out
