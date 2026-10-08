"""설정: .env 값을 읽어 Settings 하나로 묶음."""
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_key: str = ""
    mock_mode_flag: bool = True          # .env의 MOCK_MODE 값
    base_url: str = "https://clovastudio.stream.ntruss.com"
    # 모델 역할 분담
    model_analysis: str = "HCX-007"      # 분석, Structured Outputs (이미지 불가)
    model_vision: str = "HCX-005"        # 캡처 이미지 읽기
    model_light: str = "HCX-DASH-002"    # 분류 등 가벼운 호출
    timeout: float = 60
    customize_dir: Path = Path("customize")
    data_dir: Path = Path("data")
    # 크레딧 절약용 (Step 2에서 사용)
    cache_ttl: int = 3600
    max_live_calls: int = 300
    token_stop_threshold: int = 200000
    # 팀 공유용
    team_key: str = ""
    cors_origins: tuple[str, ...] = ("*",)  # 바닐라 HTML 프론트 데모용으로 기본 전체 허용

    @property
    def mock(self) -> bool:
        # MOCK_MODE=1 이거나 키가 없으면 실제 호출 안 함
        return self.mock_mode_flag or not self.api_key

    @property
    def mock_reason(self) -> str | None:
        if self.mock_mode_flag:
            return "MOCK_MODE=1"
        if not self.api_key:
            return "CLOVA_API_KEY 없음"
        return None

    @property
    def usage_log_path(self) -> Path:
        return self.data_dir / "usage_log.jsonl"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.sqlite3"

    @property
    def index_path(self) -> Path:
        # MOCK 벡터와 실제 벡터는 섞이면 안 되므로 파일 분리
        return self.data_dir / ("notices.mock.json" if self.mock else "notices.json")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        # env를 직접 넘기면(테스트용) .env 파일은 읽지 않음
        if env is None:
            load_dotenv()
            env = os.environ
        d = cls()
        origins = env.get("CORS_ORIGINS", ",".join(d.cors_origins))
        return cls(
            api_key=env.get("CLOVA_API_KEY", "").strip(),
            mock_mode_flag=env.get("MOCK_MODE", "1").strip().lower() in TRUE_VALUES,
            base_url=env.get("CLOVA_BASE_URL", d.base_url).rstrip("/"),
            model_analysis=env.get("MODEL_ANALYSIS", d.model_analysis),
            model_vision=env.get("MODEL_VISION", d.model_vision),
            model_light=env.get("MODEL_LIGHT", d.model_light),
            timeout=float(env.get("CLOVA_TIMEOUT_SECONDS", d.timeout)),
            customize_dir=Path(env.get("CUSTOMIZE_DIR", str(d.customize_dir))),
            data_dir=Path(env.get("DATA_DIR", str(d.data_dir))),
            cache_ttl=int(env.get("CACHE_TTL_SECONDS", d.cache_ttl)),
            max_live_calls=int(env.get("MAX_LIVE_CALLS", d.max_live_calls)),
            token_stop_threshold=int(env.get("TOKEN_STOP_THRESHOLD", d.token_stop_threshold)),
            team_key=env.get("TEAM_API_KEY", "").strip(),
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        )
