"""서버 상태 확인."""
from fastapi import APIRouter, Depends

from ..core import Core
from ..deps import get_core

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(core: Core = Depends(get_core)):
    """MOCK 여부·모델·인덱스 상태. 키 값 자체는 절대 내보내지 않음."""
    settings = core.settings
    return {
        "ok": True,
        "mock": settings.mock,
        "mock_reason": settings.mock_reason,
        "api_key_configured": bool(settings.api_key),
        "models": {
            "analysis": settings.model_analysis,
            "vision": settings.model_vision,
            "light": settings.model_light,
        },
        "index_file": settings.index_path.as_posix(),
        "notice_count": len(core.index.notices),
    }
