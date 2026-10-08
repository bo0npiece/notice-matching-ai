"""맞춤 공고 추천: 임베딩 검색 → 리랭커 → 규칙 판단 필터 → 점수. (AI 판단 호출 없음)"""
from ..core import Core
from .index_service import group_by_notice, notice_brief
from .judge_service import RULE_TYPES, calc_dday, count_status, judge_all
from .profile_service import normalize_profile, profile_query

SEARCH_K = 20      # 청크 검색 개수
RERANK_KEEP = 8    # 리랭커 후 남길 공고 수


def score(counts: dict, rule_total: int, rerank: float) -> float:
    """0.6 × (pass / 판단 가능한 조건 수) + 0.4 × 리랭커 점수. 규칙 조건이 없으면 비율 0.5."""
    ratio = counts["pass"] / rule_total if rule_total else 0.5
    return round(0.6 * ratio + 0.4 * rerank, 4)


async def recommend(core: Core, profile: dict, top_k: int = 5) -> dict:
    """프로필에 맞는 공고 Top k. fail 조건이 하나라도 있거나 마감 지난 공고는 제외."""
    profile = normalize_profile(profile)
    query = profile_query(profile)
    hits = await core.index.search_chunks("recommend_search", query, k=SEARCH_K)
    groups = group_by_notice(hits)
    groups = (await core.index.rerank("recommend_rerank", query, groups,
                                      key=lambda g: notice_brief(g["notice"])))[:RERANK_KEEP]

    items = []
    for g in groups:
        n = g["notice"]
        dday = calc_dday(n.get("deadline"))
        if dday is not None and dday < 0:
            continue
        judged = judge_all(n, profile)
        counts = count_status(judged)
        if counts["fail"]:
            continue
        rule_total = sum(1 for c in judged if c["type"] in RULE_TYPES)
        items.append({
            "id": n["id"],
            "title": n["title"],
            "category": n["category"],
            "score": score(counts, rule_total, g["rerank"]),
            "dday": dday,
            "benefit": n.get("benefit", ""),
            "summary": n.get("summary") or [],
            "doc_count": len(n.get("documents") or []),
            "status_count": counts,
        })
    items.sort(key=lambda x: -x["score"])
    return {"query": query, "items": items[:top_k]}
