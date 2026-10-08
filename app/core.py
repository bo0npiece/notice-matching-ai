"""기능들이 공통으로 쓰는 부품 묶음. app.state.core 에 하나만 만들어 둠."""
from dataclasses import dataclass, field

from .config import Settings
from .customize import Customize
from .hcx import HCXClient
from .services.index_service import NoticeIndex


@dataclass
class Core:
    settings: Settings
    hcx: HCXClient
    customize: Customize
    index: NoticeIndex
    explain_cache: dict = field(default_factory=dict)  # (profile hash, notice_id) → /explain 결과

    @classmethod
    def build(cls, settings: Settings) -> "Core":
        """설정으로 부품을 한 번에 만듦."""
        hcx = HCXClient(settings)
        return cls(
            settings=settings,
            hcx=hcx,
            customize=Customize(settings.customize_dir),
            index=NoticeIndex(hcx, settings.index_path),
        )
