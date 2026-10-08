"""공고 원문 근거 Q&A: 검색 → 리랭커 → RAG Reasoning(미설정 시 HCX-007)."""
from fastapi import HTTPException

from ..core import Core
from .reasoning import reason_json

NOT_FOUND = "공고에 명시되지 않았습니다."
SEARCH_K = 20   # 전체 검색 시 청크 후보 수
KEEP = 5        # 리랭커 후 근거로 쓸 청크 수


async def ask(core: Core, question: str, notice_id: str | None = None) -> dict:
    """질문에 공고 원문만 근거로 답함. notice_id가 있으면 그 공고 청크만 사용."""
    if notice_id:
        notice = core.index.get(notice_id)
        if notice is None:
            raise HTTPException(404, f"공고 {notice_id}를 찾을 수 없습니다.")
        # 공고 1개는 청크가 적으므로 전부 근거로 줌 (검색 호출 절약)
        docs = [{"notice_id": notice["id"], "title": notice["title"], "source": ch.get("source", ""),
                 "text": ch["text"]} for ch in notice.get("chunks") or []]
    else:
        hits = await core.index.search_chunks("ask_search", question, k=SEARCH_K)
        hits = (await core.index.rerank("ask_rerank", question, hits))[:KEEP]
        docs = [{"notice_id": h["notice"]["id"], "title": h["notice"]["title"], "source": h["source"],
                 "text": h["text"]} for h in hits]
    if not docs:
        return {"answer": NOT_FOUND, "sources": []}

    data = await reason_json(core, "ask", core.customize.prompt("ask"), f"## 질문\n{question}",
                             core.customize.schema("ask"), docs)
    used = [n for n in (data or {}).get("used") or [] if isinstance(n, int) and 1 <= n <= len(docs)]
    answer = (data or {}).get("answer") or NOT_FOUND
    # 근거 번호가 없으면(모른다고 답한 경우 등) 출처를 비워 둠
    return {"answer": answer, "sources": [docs[n - 1] for n in dict.fromkeys(used)]}
