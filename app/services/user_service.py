"""사용자 기능 도우미: 저장 공고 타임라인 카드, 프로필 결정."""
from fastapi import HTTPException

from ..core import Core
from .judge_service import calc_dday
from .profile_service import normalize_profile


# ---------- 라우트에서 쓰는 도우미 ----------

def saved_item(notice: dict | None, row: dict) -> dict:
    """저장 공고 1개 → 타임라인 카드 (D-day, 서류 체크리스트 포함)."""
    if notice is None:  # 인덱스에서 사라진 공고 (인덱스 재생성 등)
        return {"notice_id": row["notice_id"], "title": "(삭제된 공고)", "category": None, "deadline": None,
                "dday": None, "expired": False, "benefit": "", "url": "", "documents": [],
                "doc_count": 0, "checked_count": 0, "saved_at": row["saved_at"], "missing": True}
    docs = notice.get("documents") or []
    checked = set(row["checked"])
    dday = calc_dday(notice.get("deadline"))
    return {
        "notice_id": notice["id"], "title": notice["title"], "category": notice["category"],
        "deadline": notice.get("deadline"), "dday": dday, "expired": dday is not None and dday < 0,
        "benefit": notice.get("benefit", ""), "url": notice.get("url", ""),
        "documents": [{"name": d, "checked": d in checked} for d in docs],
        "doc_count": len(docs), "checked_count": sum(1 for d in docs if d in checked),
        "saved_at": row["saved_at"], "missing": False,
    }


def timeline_key(item: dict):
    """정렬: 마감 임박순 → 마감일 없음 → 마감 지남 → 삭제된 공고."""
    if item["missing"]:
        return (3, 0)
    if item["expired"]:
        return (2, -item["dday"])
    if item["dday"] is None:
        return (1, 0)
    return (0, item["dday"])


def resolve_profile(core: Core, profile: dict | None, user_id: str | None) -> dict:
    """요청의 profile 또는 user_id에 저장된 프로필 중 하나를 사용 (profile 우선)."""
    if profile is not None:
        return normalize_profile(profile)
    if user_id:
        return core.users.get(user_id)["profile"]
    raise HTTPException(422, "profile 또는 user_id 중 하나는 필요합니다.")
