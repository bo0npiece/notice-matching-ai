"""프로필: 자연어 → 프로필 JSON (Structured Outputs), 검색용 문장 만들기."""
from ..core import Core

PROFILE_KEYS = ("age", "region", "city", "school", "school_year", "major",
                "enrolled", "living_alone", "income", "gpa", "interests")


def normalize_profile(raw: dict) -> dict:
    """정해진 키만 남기고 빈 문자열은 null로 통일."""
    out = {}
    for key in PROFILE_KEYS:
        v = (raw or {}).get(key)
        out[key] = None if v == "" else v
    if out["interests"] is None:
        out["interests"] = []
    return out


async def parse_profile(core: Core, text: str) -> dict:
    """자연어 설명을 프로필 JSON으로 변환."""
    result = await core.hcx.chat_json(
        "profile_parse",
        core.customize.prompt("profile_parse"),
        text,
        core.customize.schema("profile"),
        max_tokens=512,
        temperature=0.1,
    )
    return normalize_profile(result.data)


def profile_query(profile: dict) -> str:
    """프로필 → 임베딩 검색용 문장. 예: "경기 용인 거주 22세 인공지능학과 3학년 재학생, 관심: AI"."""
    p = profile
    parts = []
    where = " ".join(x for x in (p.get("region"), p.get("city")) if x)
    if where:
        parts.append(f"{where} 거주")
    if p.get("age") is not None:
        parts.append(f"{p['age']}세")
    if p.get("school"):
        parts.append(p["school"])
    if p.get("major"):
        parts.append(f"{p['major']}학과" if not str(p["major"]).endswith(("과", "부")) else p["major"])
    if p.get("school_year") is not None:
        parts.append(f"{p['school_year']}학년")
    if p.get("enrolled") is True:
        parts.append("재학생")
    if p.get("living_alone") is True:
        parts.append("1인 가구 자취")
    text = " ".join(parts) or "청년"
    if p.get("interests"):
        text += ", 관심: " + ", ".join(map(str, p["interests"]))
    return text
