from pydantic import Field

from app.common.enums import BackgroundFit, BackgroundSource, BackgroundType, FontScale
from app.common.schemas import CamelModel


class BackgroundIn(CamelModel):
    type: BackgroundType = BackgroundType.NONE
    source: BackgroundSource | None = None
    preset_id: int | None = None
    asset_id: str | None = None
    fit: BackgroundFit | None = None
    opacity: int = Field(100, ge=0, le=100)
    dim: int = Field(0, ge=0, le=100)
    blur: int = Field(0, ge=0, le=100)


class ThemeIn(CamelModel):
    """전체 설정을 한 번에 저장한다."""

    background: BackgroundIn
    font_scale: FontScale = FontScale.M
    text_shadow: bool = True
    pause_on_low_power: bool = True
    autoplay_on_data_saver: bool = False
