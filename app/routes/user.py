"""사용자 API: 익명 사용자, 프로필 저장, 관심 공고·서류 체크리스트"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core import Core
from ..deps import get_core, require_team_key
from ..services.profile_service import normalize_profile
from ..services.user_service import saved_item, timeline_key

router = APIRouter(prefix="/users", tags=["user"], dependencies=[Depends(require_team_key)])


class CreateUserRequest(BaseModel):
    profile: dict | None = Field(default=None, description="처음부터 저장할 프로필 (선택)")


class ProfileBody(BaseModel):
    profile: dict


class SaveBody(BaseModel):
    notice_id: str = Field(min_length=1, max_length=20)


class ChecklistBody(BaseModel):
    checked: list[str] = Field(description="체크한 서류 이름 목록 (전체 교체)")


def _item(core: Core, user_id: str, notice_id: str) -> dict:
    """저장 공고 1개를 타임라인 카드로."""
    row = next((r for r in core.users.saved_rows(user_id) if r["notice_id"] == notice_id), None)
    if row is None:
        raise HTTPException(404, f"저장된 공고 {notice_id}가 없습니다.")
    return saved_item(core.index.get(notice_id), row)


@router.post("", status_code=201)
async def create_user(body: CreateUserRequest | None = None, core: Core = Depends(get_core)):
    """익명 사용자 생성 → user_id (프론트는 localStorage에 보관)."""
    profile = normalize_profile(body.profile) if body and body.profile else normalize_profile({})
    return core.users.create(profile)


@router.get("/{user_id}")
async def get_user(user_id: str, core: Core = Depends(get_core)):
    """사용자 프로필 조회."""
    return core.users.get(user_id)


@router.put("/{user_id}/profile")
async def put_profile(user_id: str, body: ProfileBody, core: Core = Depends(get_core)):
    """프로필 저장 (전체 교체)."""
    return core.users.update_profile(user_id, normalize_profile(body.profile))


@router.get("/{user_id}/saved")
async def get_saved(user_id: str, core: Core = Depends(get_core)):
    """관심 공고 목록 (마감 임박순, 서류 체크리스트 포함) → 마감 타임라인."""
    items = [saved_item(core.index.get(r["notice_id"]), r) for r in core.users.saved_rows(user_id)]
    return {"items": sorted(items, key=timeline_key)}


@router.post("/{user_id}/saved", status_code=201)
async def save_notice(user_id: str, body: SaveBody, core: Core = Depends(get_core)):
    """관심 공고 저장 (이미 저장돼 있으면 그대로)."""
    if core.index.get(body.notice_id) is None:
        raise HTTPException(404, f"공고 {body.notice_id}를 찾을 수 없습니다.")
    core.users.save_notice(user_id, body.notice_id)
    return {"item": _item(core, user_id, body.notice_id)}


@router.delete("/{user_id}/saved/{notice_id}")
async def remove_notice(user_id: str, notice_id: str, core: Core = Depends(get_core)):
    """관심 공고 삭제."""
    core.users.get(user_id)
    core.users.remove_notice(user_id, notice_id)
    return {"ok": True}


@router.put("/{user_id}/saved/{notice_id}/checklist")
async def put_checklist(user_id: str, notice_id: str, body: ChecklistBody, core: Core = Depends(get_core)):
    """서류 체크 상태 저장. 공고 서류 목록에 없는 이름은 무시."""
    core.users.get(user_id)
    notice = core.index.get(notice_id)
    docs = set((notice or {}).get("documents") or [])
    core.users.set_checked(user_id, notice_id, [d for d in dict.fromkeys(body.checked) if d in docs])
    return {"item": _item(core, user_id, notice_id)}
