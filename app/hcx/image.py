"""캡처 이미지 전처리: HCX 제한(20MB, 최대 2240px)에 맞춰 JPEG data URI로 변환.

HCX dataUri.data에는 'data:image/jpeg;base64,' 접두어가 반드시 있어야 함 (없으면 400 Invalid parameter).
"""
import base64
import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 20 * 1024 * 1024
MAX_SIDE = 2240
MAX_RATIO = 5  # 가로세로 비율 5:1 초과 시 흰 여백 추가


def prepare_image(raw: bytes) -> str:
    """이미지 바이트 → 'data:image/jpeg;base64,...' 문자열. 잘못된 이미지면 ValueError."""
    if len(raw) > MAX_BYTES:
        raise ValueError("이미지는 20MB 이하로 올려 주세요.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as original:
                if original.format not in {"PNG", "JPEG", "WEBP", "BMP"}:
                    raise ValueError
                if original.width < 4 or original.height < 4:
                    raise ValueError
                image = ImageOps.exif_transpose(original).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError("PNG/JPEG/WEBP/BMP 이미지(4px 이상)를 올려 주세요.") from None

    image.thumbnail((MAX_SIDE, MAX_SIDE))
    w, h = image.size
    size = (max(w, -(-h // MAX_RATIO)), max(h, -(-w // MAX_RATIO)))
    if size != image.size:
        image = ImageOps.pad(image, size, color="white")

    out = io.BytesIO()
    image.save(out, format="JPEG", quality=90)  # 원본 메타데이터는 버림
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


# base64 앞부분으로 형식 추정 (접두어 없이 들어온 경우 대비)
_SIGNATURES = {"/9j/": "jpeg", "iVBOR": "png", "UklGR": "webp", "Qk": "bmp"}


def as_data_uri(value: str) -> str:
    """접두어가 없으면 'data:image/<형식>;base64,'를 붙임."""
    if value.startswith("data:"):
        return value
    kind = next((k for sig, k in _SIGNATURES.items() if value.startswith(sig)), "jpeg")
    return f"data:image/{kind};base64,{value}"
