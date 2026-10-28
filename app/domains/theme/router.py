from fastapi import APIRouter, File, Response, UploadFile

from app.common.enums import BackgroundType
from app.common.ratelimit import check_user_limit
from app.core.config import settings
from app.core.dependencies import DB, CurrentUser
from app.domains.theme import service
from app.domains.theme.schemas import ThemeIn

router = APIRouter(tags=["theme"])


@router.get("/me/theme")
async def get_theme(db: DB, user: CurrentUser):
    return await service.get_theme(db, user)


@router.put("/me/theme")
async def save_theme(body: ThemeIn, db: DB, user: CurrentUser):
    return await service.save_theme(db, user, body)


@router.delete("/me/theme")
async def reset_theme(db: DB, user: CurrentUser):
    return await service.reset_theme(db, user)


@router.get("/theme/presets")
async def presets(db: DB, user: CurrentUser, type: BackgroundType | None = None):
    return await service.list_presets(db, type)


@router.post("/me/theme/assets", status_code=201)
async def upload_asset(db: DB, user: CurrentUser, file: UploadFile = File(...)):
    check_user_limit(user.user_id, "upload", settings.rate_upload_per_min)
    return await service.upload_asset(db, user, file)


@router.delete("/me/theme/assets/{asset_id}", status_code=204)
async def delete_asset(asset_id: str, db: DB, user: CurrentUser):
    await service.delete_asset(db, user, asset_id)
    return Response(status_code=204)
