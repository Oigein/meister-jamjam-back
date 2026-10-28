from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import BackgroundFit, BackgroundSource, BackgroundType, FontScale
from app.common.ids import new_id
from app.common.timeutil import now_kst
from app.core.database import Base, enum_col


class ThemePreset(Base):
    __tablename__ = "ThemePresets"

    preset_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[BackgroundType] = mapped_column(enum_col(BackgroundType))
    name: Mapped[str] = mapped_column(String(50))
    file_url: Mapped[str] = mapped_column(String(500))
    thumbnail_url: Mapped[str | None] = mapped_column(String(500))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ThemeAsset(Base):
    __tablename__ = "ThemeAssets"

    asset_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("Users.user_id"), index=True)
    type: Mapped[BackgroundType] = mapped_column(enum_col(BackgroundType))
    file_key: Mapped[str] = mapped_column(String(255))
    thumbnail_key: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    duration_sec: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(default=now_kst)


class UserTheme(Base):
    __tablename__ = "UserThemes"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("Users.user_id"), primary_key=True)
    background_type: Mapped[BackgroundType] = mapped_column(enum_col(BackgroundType), default=BackgroundType.NONE)
    background_source: Mapped[BackgroundSource | None] = mapped_column(enum_col(BackgroundSource))
    preset_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("ThemePresets.preset_id"))
    asset_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ThemeAssets.asset_id"))
    fit: Mapped[BackgroundFit] = mapped_column(enum_col(BackgroundFit), default=BackgroundFit.COVER)
    opacity: Mapped[int] = mapped_column(Integer, default=100)
    dim: Mapped[int] = mapped_column(Integer, default=0)
    blur: Mapped[int] = mapped_column(Integer, default=0)
    font_scale: Mapped[FontScale] = mapped_column(enum_col(FontScale), default=FontScale.M)
    text_shadow: Mapped[bool] = mapped_column(Boolean, default=True)
    pause_on_low_power: Mapped[bool] = mapped_column(Boolean, default=True)
    autoplay_on_data_saver: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(default=now_kst)
