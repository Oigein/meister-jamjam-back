from fastapi import APIRouter, Depends

from app.common.ratelimit import check_user_limit
from app.core.config import settings
from app.core.dependencies import DB, CurrentUser, StudentUser
from app.domains.user import service
from app.domains.user.schemas import ProfileUpdate

router = APIRouter(tags=["user"])


@router.get("/me")
async def get_me(db: DB, user: CurrentUser):
    return await service.me(db, user)


@router.get("/me/profile")
async def get_my_profile(db: DB, user: CurrentUser):
    return await service.get_profile(db, user)


@router.patch("/me/profile")
async def update_my_profile(body: ProfileUpdate, db: DB, user: CurrentUser):
    check_user_limit(user.user_id, "profile", settings.rate_profile_per_min)
    return await service.update_profile(db, user, body)


@router.get("/teachers")
async def search_teachers(
    db: DB, user: CurrentUser, q: str | None = None, subject: str | None = None, position: str | None = None
):
    return await service.search_teachers(db, q, subject, position)


@router.get("/classes/{grade}/{class_no}/students")
async def class_roster(grade: int, class_no: int, db: DB, user: CurrentUser):
    return await service.class_roster(db, grade, class_no)
