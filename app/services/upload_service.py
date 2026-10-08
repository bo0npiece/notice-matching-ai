"""공고 구조화 공통 로직 + 포스터 업로드: 이미지 → HCX-005 텍스트 → HCX-007 구조화 → 임베딩 → 인덱스 추가."""
import logging
import re
from datetime import date

from fastapi import HTTPException

from ..core import Core
from ..customize import Customize
from ..hcx import HCXClient
from ..hcx.image import prepare_image

log = logging.getLogger("notice")
SECTION = re.compile(r"^\s*(\d+)\s*[.)]\s*(.*)")  # "2. 지원 자격" 형태의 항 시작


def split_chunks(text: str) -> list[dict]:
    """원문을 항 단위 청크로 나눔. 첫 항 앞부분은 source="개요"."""
    # TODO: CLOVA 문단 나누기 API 경로 확인 후 교체 가능 (지금은 번호 항 기준 규칙 분할)
    chunks, source, lines = [], "개요", []

    def flush():
        body = "\n".join(lines).strip()
        if body:
            chunks.append({"text": body, "source": source})

    for line in text.splitlines():
        m = SECTION.match(line)
        if m:
            flush()
            source, lines = f"{m.group(1)}항", [line.strip()]
        else:
            lines.append(line.rstrip())
    flush()
    return chunks


async def structure_notice(hcx: HCXClient, customize: Customize, notice_id: str, raw: str,
                           mock_sample: str | None = None) -> dict:
    """공고 원문 1개 → notice dict (Structured Outputs 결과 + chunks·emb)."""
    system = customize.prompt("notice_structure", today=date.today().isoformat(),
                              summary_rules=customize.prompt("summary"))
    result = await hcx.chat_json("notice_structure", system, raw, customize.schema("notice"),
                                 max_tokens=3000, temperature=0.1, mock_sample=mock_sample)
    notice = {"id": notice_id, **result.data}
    chunks = split_chunks(raw)
    for chunk in chunks:
        # 공고 제목을 앞에 붙여 임베딩 → 어떤 공고의 조각인지 검색에 반영
        chunk["emb"] = (await hcx.embed("index_embed", f"{notice['title']}\n{chunk['text']}")).data
    notice["chunks"] = chunks
    return notice


def public_notice(notice: dict) -> dict:
    """응답용 공고: 임베딩 벡터는 빼고 보냄."""
    return {**notice, "chunks": [{"text": c["text"], "source": c.get("source", "")}
                                 for c in notice.get("chunks") or []]}


async def upload_notice(core: Core, raw: bytes) -> dict:
    """포스터 이미지 1장 → 새 공고를 만들어 인덱스에 추가.
    MOCK에서는 메모리에만 추가(커밋된 notices.mock.json을 건드리지 않음)."""
    try:
        data_uri = prepare_image(raw)
    except ValueError as error:
        raise HTTPException(400, str(error)) from None

    ocr = await core.hcx.read_image("upload_ocr", core.customize.prompt("ocr"), image_b64=data_uri,
                                    max_tokens=2048, mock_sample="upload_ocr")
    text = ocr.text.strip()
    if len(text) < 20:
        raise HTTPException(422, "이미지에서 공고 내용을 충분히 읽지 못했습니다. 더 선명한 이미지를 올려 주세요.")

    notice_id = core.index.next_id()
    notice = await structure_notice(core.hcx, core.customize, notice_id, text, mock_sample="upload_notice")
    notice["origin"] = "upload"
    if not core.settings.mock:
        # 원문도 남겨 두면 build_index.py로 다시 만들 수 있음
        path = core.settings.customize_dir / "knowledge" / "notices" / f"{notice_id}.txt"
        path.write_text(text, encoding="utf-8")
    core.index.add(notice, persist=not core.settings.mock)
    log.info("공고 업로드 추가: %s %s", notice_id, notice.get("title"))
    return {"notice": public_notice(notice)}
