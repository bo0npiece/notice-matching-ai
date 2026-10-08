"""자격 판단: 규칙 판단(코드) + text 조건 AI 판단(RAG Reasoning)."""
import hashlib
import json
from datetime import date

from fastapi import HTTPException

from ..core import Core
from .profile_service import normalize_profile
from .reasoning import reason_json

RULE_TYPES = ("range", "in", "bool")

# 시·도 표기 정규화 ("경기도" → "경기", "서울특별시" → "서울")
REGION_ALIASES = {
    "서울특별시": "서울", "서울시": "서울", "부산광역시": "부산", "대구광역시": "대구",
    "인천광역시": "인천", "광주광역시": "광주", "대전광역시": "대전", "울산광역시": "울산",
    "세종특별자치시": "세종", "세종시": "세종", "경기도": "경기", "강원도": "강원",
    "강원특별자치도": "강원", "충청북도": "충북", "충청남도": "충남", "전라북도": "전북",
    "전북특별자치도": "전북", "전라남도": "전남", "경상북도": "경북", "경상남도": "경남",
    "제주도": "제주", "제주특별자치도": "제주",
}


def normalize_region(value) -> str:
    """지역명 표기 차이 정규화. "경기도"/"경기" → "경기", "용인시" → "용인"."""
    v = str(value).strip().replace(" ", "")
    if v in REGION_ALIASES:
        return REGION_ALIASES[v]
    for suffix in ("특별자치도", "특별자치시", "광역시", "특별시", "도", "시", "군", "구"):
        if v.endswith(suffix) and len(v) > len(suffix) + 1:
            return v[: -len(suffix)]
    return v


def _match_in(key: str, v, values: list, profile: dict) -> bool:
    """in 조건 비교. region은 시·도와 시·군 모두 비교, 문자열은 부분 일치 허용."""
    if key == "region":
        mine = {normalize_region(x) for x in (v, profile.get("city")) if x}
        return any(normalize_region(x) in mine for x in values)
    if isinstance(v, str):
        return any(isinstance(x, str) and (x in v or v in x) for x in values)
    return v in values


def judge_rule(cond: dict, profile: dict) -> str:
    """조건 1개를 프로필과 코드로 비교 → pass / fail / unknown / ai(text 조건)."""
    v = profile.get(cond["key"])
    if cond["type"] == "text":
        return "ai"
    if v is None:
        return "unknown"
    try:
        if cond["type"] == "range":
            lo, hi = cond.get("min"), cond.get("max")
            ok = (lo is None or v >= lo) and (hi is None or v <= hi)
        elif cond["type"] == "in":
            ok = _match_in(cond["key"], v, cond.get("values") or [], profile)
        elif cond["type"] == "bool":
            ok = v == cond.get("value")
        else:
            return "unknown"
    except TypeError:
        return "unknown"  # 프로필 값 형식이 이상하면 단정하지 않음
    return "pass" if ok else "fail"


def judge_all(notice: dict, profile: dict) -> list[dict]:
    """공고의 모든 조건에 judge_rule 적용. 조건 사본에 status를 붙여 반환."""
    return [{**c, "status": judge_rule(c, profile)} for c in notice.get("conditions") or []]


def count_status(judged: list[dict]) -> dict:
    """상태별 개수 {"pass","fail","unknown","ai"}."""
    counts = {"pass": 0, "fail": 0, "unknown": 0, "ai": 0}
    for c in judged:
        counts[c["status"]] += 1
    return counts


def calc_dday(deadline: str | None, today: date | None = None) -> int | None:
    """마감일까지 남은 일수. 마감일 없으면 None, 지났으면 음수."""
    if not deadline:
        return None
    try:
        return (date.fromisoformat(deadline) - (today or date.today())).days
    except ValueError:
        return None


# ---------- /explain: 조건별 판단 + 이유 ----------

KEY_LABELS = {"age": "나이", "region": "거주 지역", "school_year": "학년", "major": "전공",
              "enrolled": "재학 여부", "income": "소득", "gpa": "평점", "etc": "기타"}
STATUS_OK = ("pass", "fail", "unknown")


def rule_reason(cond: dict, status: str, profile: dict) -> str:
    """규칙 판단 결과에 붙일 한 줄 이유."""
    label = KEY_LABELS.get(cond["key"], cond["key"])
    v = profile.get(cond["key"])
    if status == "unknown":
        return f"프로필에 {label} 정보가 없어 확인이 필요합니다."
    if cond["key"] == "region":
        v = " ".join(x for x in (profile.get("region"), profile.get("city")) if x)
    if isinstance(v, bool):
        v = "예" if v else "아니오"
    mark = "충족" if status == "pass" else "미충족"
    return f"내 {label}: {v} → 조건 '{cond.get('text', '')}' {mark}"


def profile_hash(profile: dict) -> str:
    """캐시 키용 프로필 해시."""
    return hashlib.sha256(json.dumps(profile, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


async def explain(core: Core, profile: dict, notice_id: str) -> dict:
    """공고 1개의 조건별 pass/fail/unknown + 이유 + 출처. text 조건만 AI 판단."""
    profile = normalize_profile(profile)
    notice = core.index.get(notice_id)
    if notice is None:
        raise HTTPException(404, f"공고 {notice_id}를 찾을 수 없습니다.")
    key = (profile_hash(profile), notice_id)
    if key in core.explain_cache:
        return core.explain_cache[key]

    judged = judge_all(notice, profile)
    rows = [{"text": c.get("text", ""), "status": c["status"], "source": c.get("source", ""),
             "reason": "" if c["status"] == "ai" else rule_reason(c, c["status"], profile),
             "by": "ai" if c["status"] == "ai" else "rule"} for c in judged]

    ai_rows = [i for i, c in enumerate(judged) if c["status"] == "ai"]
    if ai_rows:
        listing = "\n".join(f"{n}. {judged[i].get('text', '')} (출처: {judged[i].get('source', '')})"
                            for n, i in enumerate(ai_rows))
        system = core.customize.prompt("judge", profile=json.dumps(profile, ensure_ascii=False),
                                       conditions=listing)
        docs = [{"title": notice["title"], "source": ch.get("source", ""), "text": ch["text"]}
                for ch in notice.get("chunks") or []]
        data = await reason_json(core, "explain_judge", system, "위 조건들을 각각 판단하라.",
                                 core.customize.schema("judge"), docs)
        answers = {r.get("index"): r for r in (data or {}).get("results") or [] if isinstance(r, dict)}
        for n, i in enumerate(ai_rows):
            r = answers.get(n) or {}
            status = r.get("status") if r.get("status") in STATUS_OK else "unknown"
            rows[i]["status"] = status
            rows[i]["reason"] = r.get("reason") or "공고 원문만으로 판단하기 어려워 확인이 필요합니다."

    result = {
        "notice_id": notice_id,
        "title": notice["title"],
        "category": notice["category"],
        "benefit": notice.get("benefit", ""),
        "url": notice.get("url", ""),
        "conditions": rows,
        "status_count": count_status(rows),
        "documents": notice.get("documents") or [],
        "deadline": notice.get("deadline"),
        "dday": calc_dday(notice.get("deadline")),
    }
    core.explain_cache[key] = result
    return result
