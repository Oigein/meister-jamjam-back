from fastapi import UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import BackgroundFit, BackgroundSource, BackgroundType, FontScale
from app.common.exceptions import AppException, conflict, not_found, validation_failed
from app.common.filetype import sniff
from app.common.ids import is_uuid, new_id
from app.common.storage import public_storage
from app.common.timeutil import now_kst, to_iso
from app.core.config import settings
from app.domains.theme import media
from app.domains.theme.models import ThemeAsset, ThemePreset, UserTheme
from app.domains.theme.schemas import ThemeIn
from app.domains.user.models import User


def _invalid_background(message: str = "배경 설정이 올바르지 않습니다.") -> AppException:
    return AppException(400, "INVALID_BACKGROUND", message)


def _defaults() -> dict:
    return {
        "background": {
            "type": BackgroundType.NONE.value,
            "source": None,
            "presetId": None,
            "assetId": None,
            "url": None,
            "thumbnailUrl": None,
            "fit": BackgroundFit.COVER.value,
            "opacity": 100,
            "dim": 0,
            "blur": 0,
        },
        "fontScale": FontScale.M.value,
        "textShadow": True,
        "pauseOnLowPower": True,
        "autoplayOnDataSaver": False,
        "updatedAt": None,
    }


def _asset_urls(asset: ThemeAsset) -> tuple[str | None, str | None]:
    storage = public_storage()
    return storage.url(asset.file_key), storage.url(asset.thumbnail_key)


async def _out(db: AsyncSession, t: UserTheme | None) -> dict:
    if t is None:
        return _defaults()
    url = thumb = None
    if t.background_type != BackgroundType.NONE:
        if t.background_source == BackgroundSource.PRESET and t.preset_id is not None:
            preset = await db.get(ThemePreset, t.preset_id)
            url, thumb = (preset.file_url, preset.thumbnail_url) if preset else (None, None)
        elif t.background_source == BackgroundSource.UPLOAD and t.asset_id is not None:
            asset = await db.get(ThemeAsset, t.asset_id)
            url, thumb = _asset_urls(asset) if asset else (None, None)
    none = t.background_type == BackgroundType.NONE
    return {
        "background": {
            "type": t.background_type.value,
            "source": None if none else (t.background_source.value if t.background_source else None),
            "presetId": None if none else t.preset_id,
            "assetId": None if none else t.asset_id,
            "url": url,
            "thumbnailUrl": thumb,
            "fit": t.fit.value,
            "opacity": t.opacity,
            "dim": t.dim,
            "blur": t.blur,
        },
        "fontScale": t.font_scale.value,
        "textShadow": t.text_shadow,
        "pauseOnLowPower": t.pause_on_low_power,
        "autoplayOnDataSaver": t.autoplay_on_data_saver,
        "updatedAt": to_iso(t.updated_at),
    }


async def get_theme(db: AsyncSession, user: User) -> dict:
    return await _out(db, await db.get(UserTheme, user.user_id))


async def save_theme(db: AsyncSession, user: User, body: ThemeIn) -> dict:
    bg = body.background
    source = preset_id = asset_id = None
    fit = bg.fit or BackgroundFit.COVER
    if bg.type != BackgroundType.NONE:
        if bg.source == BackgroundSource.PRESET:
            preset = await db.get(ThemePreset, bg.preset_id) if bg.preset_id is not None else None
            if preset is None or preset.type != bg.type:
                raise _invalid_background("기본 제공 배경을 찾을 수 없거나 종류가 다릅니다.")
            source, preset_id = BackgroundSource.PRESET, preset.preset_id
        elif bg.source == BackgroundSource.UPLOAD:
            asset = await db.get(ThemeAsset, bg.asset_id) if bg.asset_id and is_uuid(bg.asset_id) else None
            if asset is None or asset.user_id != user.user_id or asset.type != bg.type:
                raise _invalid_background("업로드한 배경 파일을 찾을 수 없거나 종류가 다릅니다.")
            source, asset_id = BackgroundSource.UPLOAD, asset.asset_id
        else:
            raise _invalid_background()
        if bg.type == BackgroundType.MP4:
            fit = BackgroundFit.COVER  # MP4는 항상 COVER (다른 값은 무시)

    theme = await db.get(UserTheme, user.user_id)
    if theme is None:
        theme = UserTheme(user_id=user.user_id)
        db.add(theme)
    theme.background_type = bg.type
    theme.background_source = source
    theme.preset_id = preset_id
    theme.asset_id = asset_id
    theme.fit = fit
    theme.opacity, theme.dim, theme.blur = bg.opacity, bg.dim, bg.blur
    theme.font_scale = body.font_scale
    theme.text_shadow = body.text_shadow
    theme.pause_on_low_power = body.pause_on_low_power
    theme.autoplay_on_data_saver = body.autoplay_on_data_saver
    theme.updated_at = now_kst()
    await db.commit()
    return await _out(db, theme)


async def reset_theme(db: AsyncSession, user: User) -> dict:
    # 업로드한 파일은 지우지 않는다 (다시 선택할 수 있게)
    await db.execute(delete(UserTheme).where(UserTheme.user_id == user.user_id))
    await db.commit()
    return _defaults()


async def list_presets(db: AsyncSession, type_: BackgroundType | None) -> dict:
    stmt = select(ThemePreset).order_by(ThemePreset.sort_order, ThemePreset.preset_id)
    if type_ is not None:
        stmt = stmt.where(ThemePreset.type == type_)
    return {
        "items": [
            {
                "presetId": p.preset_id,
                "type": p.type.value,
                "name": p.name,
                "url": p.file_url,
                "thumbnailUrl": p.thumbnail_url,
            }
            for p in (await db.scalars(stmt)).all()
        ]
    }


async def upload_asset(db: AsyncSession, user: User, file: UploadFile) -> dict:
    limit = settings.theme_mp4_max_bytes
    data = await file.read(limit + 1)
    kind = sniff(data)  # 파일 내용으로 형식 판별
    if kind not in ("image/gif", "video/mp4"):
        raise AppException(415, "UNSUPPORTED_FILE_TYPE", "GIF 또는 MP4 파일만 올릴 수 있습니다.")
    is_gif = kind == "image/gif"
    if len(data) > (settings.theme_gif_max_bytes if is_gif else settings.theme_mp4_max_bytes):
        raise AppException(413, "FILE_TOO_LARGE", "파일이 너무 큽니다. 압축한 뒤 다시 올려 주세요.")

    duration = None
    if is_gif:
        thumb = media.gif_thumbnail(data)
        if thumb is None:
            raise AppException(415, "UNSUPPORTED_FILE_TYPE", "올바른 GIF 파일이 아닙니다.")
    else:
        duration = media.mp4_duration(data)
        if duration is None:
            raise AppException(415, "UNSUPPORTED_FILE_TYPE", "올바른 MP4 파일이 아닙니다.")
        if duration > settings.theme_mp4_max_seconds:
            raise AppException(400, "VIDEO_TOO_LONG", f"영상은 {int(settings.theme_mp4_max_seconds)}초 이하여야 합니다.")

    count = await db.scalar(select(func.count()).select_from(ThemeAsset).where(ThemeAsset.user_id == user.user_id))
    if (count or 0) >= settings.theme_asset_limit:
        raise conflict("ASSET_LIMIT_EXCEEDED", "업로드한 파일이 너무 많습니다. 기존 파일을 삭제해 주세요.")

    if not is_gif:
        thumb = await media.mp4_thumbnail(data)
        data = await media.strip_audio(data)  # 저장 시 오디오 트랙 제거
    storage = public_storage()
    file_key = await storage.save(data, "themes", "gif" if is_gif else "mp4")
    thumb_key = await storage.save(thumb, "themes", "jpg") if thumb else None
    asset = ThemeAsset(
        asset_id=new_id(),
        user_id=user.user_id,
        type=BackgroundType.GIF if is_gif else BackgroundType.MP4,
        file_key=file_key,
        thumbnail_key=thumb_key,
        size_bytes=len(data),
        duration_sec=round(duration, 2) if duration is not None else None,
        created_at=now_kst(),
    )
    db.add(asset)
    await db.commit()
    url, thumb_url = _asset_urls(asset)
    return {
        "assetId": asset.asset_id,
        "type": asset.type.value,
        "url": url,
        "thumbnailUrl": thumb_url,
        "sizeBytes": asset.size_bytes,
        "durationSec": asset.duration_sec,
    }


async def delete_asset(db: AsyncSession, user: User, asset_id: str) -> None:
    asset = await db.get(ThemeAsset, asset_id) if is_uuid(asset_id) else None
    if asset is None or asset.user_id != user.user_id:
        raise not_found("ASSET_NOT_FOUND", "파일을 찾을 수 없습니다.")
    theme = await db.get(UserTheme, user.user_id)
    if theme is not None and theme.asset_id == asset.asset_id:
        # 현재 배경으로 쓰는 파일이면 배경만 NONE으로 바꾸고 나머지 설정은 유지
        theme.background_type = BackgroundType.NONE
        theme.background_source = None
        theme.asset_id = None
        theme.updated_at = now_kst()
        await db.flush()
    keys = [asset.file_key, asset.thumbnail_key]
    await db.delete(asset)
    await db.commit()
    for key in keys:
        await public_storage().delete(key)


__all__ = ["validation_failed"]
