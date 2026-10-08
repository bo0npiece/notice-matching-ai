"""근거 기반 판단·답변 공통 호출: RAG Reasoning 우선, 경로 미설정이면 HCX-007 Structured Outputs로 대체."""
import logging

from ..core import Core
from ..hcx import HCXError

log = logging.getLogger("notice")


def format_docs(docs: list[dict]) -> str:
    """원문 조각을 [번호] (공고명 · 위치) 본문 형식으로 묶음."""
    return "\n\n".join(f"[{i}] ({d['title']} · {d['source']})\n{d['text']}" for i, d in enumerate(docs, 1))


async def reason_json(core: Core, feature: str, system: str, user: str, schema: dict,
                      docs: list[dict], max_tokens: int = 1024) -> dict:
    """docs(공고 원문 조각)만 근거로 schema 형식 JSON을 받음."""
    try:
        result = await core.hcx.rag_reasoning(
            feature, user, [{"id": str(i), "text": d["text"]} for i, d in enumerate(docs, 1)])
        if isinstance(result.data, dict):
            return result.data
    except HCXError as error:
        if error.status_code != 501:
            raise
        log.warning("RAG Reasoning 미설정 → HCX-007 Structured Outputs로 대체 (%s)", feature)
    content = f"{user}\n\n## 공고 원문\n{format_docs(docs)}"
    result = await core.hcx.chat_json(feature, system, content, schema,
                                      max_tokens=max_tokens, temperature=0.1)
    return result.data
