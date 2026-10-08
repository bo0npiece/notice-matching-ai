import uuid

import httpx
from fastapi import HTTPException

from .settings import Settings


class ClovaProvider:
    """HyperCLOVA X만 호출. 외부 모델로의 fallback은 없습니다."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def complete(self, payload: dict, model: str) -> dict:
        if not self.settings.api_key:
            raise HTTPException(503, "CLOVA_API_KEY를 .env에 설정하세요.")
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "X-NCP-CLOVASTUDIO-REQUEST-ID": str(uuid.uuid4()),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        # 타임아웃/5xx 자동 재시도는 중복 과금을 피하려고 하지 않습니다.
        try:
            async with httpx.AsyncClient(timeout=self.settings.timeout) as client:
                response = await client.post(
                    f"{self.settings.base_url}/v3/chat-completions/{model}",
                    headers=headers, json=payload,
                )
        except httpx.TimeoutException:
            raise HTTPException(504, "CLOVA 응답 시간 초과. 사용량은 공급자 콘솔에서도 확인하세요.") from None
        except httpx.RequestError:
            raise HTTPException(502, "CLOVA 연결 실패. 네트워크와 API 주소를 확인하세요.") from None
        if response.status_code != 200:
            hint = {401: "API 키 확인", 403: "모델 사용 권한 확인", 429: "호출 제한: 잠시 후 재시도"}.get(response.status_code, "공급자 오류")
            raise HTTPException(502, f"CLOVA HTTP {response.status_code}: {hint}")
        try:
            data = response.json()
            code = str(data["status"]["code"])
            if code != "20000":
                raise HTTPException(502, f"CLOVA 오류 코드 {code}")
            result = data["result"]
            if not isinstance(result["message"]["content"], str):
                raise ValueError()
            return result
        except (KeyError, TypeError, ValueError):
            raise HTTPException(502, "CLOVA 응답 형식이 예상과 다릅니다. 지급 API 사양을 확인하세요.") from None
