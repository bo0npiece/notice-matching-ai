"""공고 비서 API: /profile, /recommend, /explain, /ask, /notice/upload, /notices, /usage"""
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from ..core import Core
from ..deps import get_core, require_team_key
from ..services.ask_service import ask
from ..services.judge_service import calc_dday, explain
from ..services.profile_service import parse_profile
from ..services.recommend_service import recommend
from ..services.upload_service import public_notice, upload_notice
from ..services.usage_service import usage_report

router = APIRouter(tags=["notice"], dependencies=[Depends(require_team_key)])


class ProfileRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000, description="자연어 자기소개")


class RecommendRequest(BaseModel):
    profile: dict = Field(description="POST /profile 결과의 profile")
    top_k: int = Field(default=5, ge=1, le=20)


class ExplainRequest(BaseModel):
    profile: dict = Field(description="사용자 프로필")
    notice_id: str = Field(min_length=1, max_length=20)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    notice_id: str | None = Field(default=None, description="있으면 그 공고 원문만 근거로 사용")


@router.post("/profile")
async def post_profile(body: ProfileRequest, core: Core = Depends(get_core)):
    """자연어 → 프로필 JSON."""
    return {"profile": await parse_profile(core, body.text)}


@router.post("/recommend")
async def post_recommend(body: RecommendRequest, core: Core = Depends(get_core)):
    """프로필 맞춤 공고 추천."""
    return await recommend(core, body.profile, body.top_k)


@router.post("/explain")
async def post_explain(body: ExplainRequest, core: Core = Depends(get_core)):
    """공고 1개의 조건별 ✅❌❓ + 이유 + 출처."""
    return await explain(core, body.profile, body.notice_id)


@router.post("/ask")
async def post_ask(body: AskRequest, core: Core = Depends(get_core)):
    """공고 원문 근거 질문 답변."""
    return await ask(core, body.question, body.notice_id)


@router.post("/notice/upload")
async def post_notice_upload(file: UploadFile = File(..., description="공고 포스터·캡처 이미지"),
                             core: Core = Depends(get_core)):
    """포스터 이미지 → 구조화 → 인덱스에 추가."""
    return await upload_notice(core, await file.read())


@router.get("/notices/{notice_id}")
async def get_notice(notice_id: str, core: Core = Depends(get_core)):
    """공고 1개 상세 (원문 청크 포함, 임베딩 제외)."""
    notice = core.index.get(notice_id)
    if notice is None:
        raise HTTPException(404, f"공고 {notice_id}를 찾을 수 없습니다.")
    return {"notice": {**public_notice(notice), "dday": calc_dday(notice.get("deadline"))}}


@router.get("/usage")
async def get_usage(recent: int = Query(50, ge=0, le=500), core: Core = Depends(get_core)):
    """HCX 토큰 사용량 (호출명별 합계 + 최근 로그)."""
    return usage_report(core, recent)


@router.get("/notices")
async def get_notices(core: Core = Depends(get_core)):
    """전체 공고 목록 (id, title, category, deadline, dday)."""
    return {"items": [{
        "id": n["id"], "title": n["title"], "category": n["category"],
        "deadline": n.get("deadline"), "dday": calc_dday(n.get("deadline")),
    } for n in core.index.notices]}
