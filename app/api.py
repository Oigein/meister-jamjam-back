from fastapi import APIRouter

from app.domains.auth.router import router as auth_router
from app.domains.contest.router import router as contest_router
from app.domains.game.router import router as game_router
from app.domains.merit.router import router as merit_router
from app.domains.mileage.router import router as mileage_router
from app.domains.notification.router import router as notification_router
from app.domains.report.router import router as report_router
from app.domains.theme.router import router as theme_router
from app.domains.user.router import router as user_router

api_router = APIRouter(prefix="/api")
for r in (
    user_router,
    merit_router,
    mileage_router,
    contest_router,
    report_router,
    notification_router,
    theme_router,
    game_router,
):
    api_router.include_router(r)

__all__ = ["api_router", "auth_router"]
