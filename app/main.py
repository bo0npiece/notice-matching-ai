"""FastAPI 앱 조립. 실행: uvicorn app.main:app"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .config import Settings
from .core import Core
from .customize import CustomizeError
from .hcx import HCXError
from .routes import health, notice, user

log = logging.getLogger("notice")


class UTF8JSONResponse(JSONResponse):
    """charset을 명시해 PowerShell 5.1 등에서 한글이 깨지지 않게 함."""
    media_type = "application/json; charset=utf-8"


def create_app(settings: Settings | None = None) -> FastAPI:
    """앱 생성. 모든 에러는 {"error": "..."} 형식으로 응답."""
    settings = settings or Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="공고 비서 API", version="0.1.0", default_response_class=UTF8JSONResponse)
    app.state.core = Core.build(settings)

    @app.exception_handler(HCXError)
    async def hcx_error(request: Request, error: HCXError):
        log.error("HCX 호출 실패 %s %s: %s", request.method, request.url.path, error.message)
        return UTF8JSONResponse(status_code=error.status_code, content={"error": error.message})

    @app.exception_handler(CustomizeError)
    async def customize_error(request: Request, error: CustomizeError):
        log.error("customize 설정 오류: %s", error)
        return UTF8JSONResponse(status_code=500, content={"error": f"customize 설정 오류: {error}"})

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        return UTF8JSONResponse(status_code=error.status_code, content={"error": str(error.detail)})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        first = error.errors()[0] if error.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", []) if x != "body")
        return UTF8JSONResponse(status_code=422, content={"error": f"요청 형식 오류: {where} {first.get('msg', '')}".strip()})

    # 프론트는 바닐라 HTML/JS → 기본값 CORS_ORIGINS=* (전체 허용)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-Team-Key"],
    )

    app.include_router(health.router)
    app.include_router(notice.router)
    app.include_router(user.router)
    return app


app = create_app()
