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
from ..services.user_service import resolve_profile

router = APIRouter(tags=["notice"], dependencies=[Depends(require_team_key)])


class ProfileRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000, description="자연어 자기소개")
    user_id: str | None = Field(default=None, description="주면 변환된 프로필을 그 사용자에게 저장")


class RecommendRequest(BaseModel):
    profile: dict | None = Field(default=None, description="프로필 (없으면 user_id의 저장된 프로필)")
    user_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class ExplainRequest(BaseModel):
    profile: dict | None = Field(default=None, description="프로필 (없으면 user_id의 저장된 프로필)")
    user_id: str | None = None
    notice_id: str = Field(min_length=1, max_length=20)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    notice_id: str | None = Field(default=None, description="있으면 그 공고 원문만 근거로 사용")


@router.post("/profile")
async def post_profile(body: ProfileRequest, core: Core = Depends(get_core)):
    """자연어 → 프로필 JSON. user_id가 있으면 저장까지."""
    if body.user_id:
        core.users.get(body.user_id)  # 없는 사용자면 AI 호출 전에 404
    profile = await parse_profile(core, body.text)
    if body.user_id:
        core.users.update_profile(body.user_id, profile)
    return {"profile": profile}


@router.post("/recommend")
async def post_recommend(body: RecommendRequest, core: Core = Depends(get_core)):
    """프로필 맞춤 공고 추천."""
    return await recommend(core, resolve_profile(core, body.profile, body.user_id), body.top_k)


@router.post("/explain")
async def post_explain(body: ExplainRequest, core: Core = Depends(get_core)):
    """공고 1개의 조건별 ✅❌❓ + 이유 + 출처."""
    return await explain(core, resolve_profile(core, body.profile, body.user_id), body.notice_id)


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
