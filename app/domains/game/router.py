from fastapi import APIRouter, Query

from app.common.enums import DrawType
from app.common.params import opt_int
from app.core.dependencies import DB, CurrentUser
from app.domains.game import service
from app.domains.game.schemas import PinballBody, SeatDrawBody

router = APIRouter(tags=["game"])


@router.post("/draws/seats", status_code=201)
async def draw_seats(body: SeatDrawBody, db: DB, user: CurrentUser):
    return await service.draw_seats(db, user, body)


@router.post("/draws/pinball", status_code=201)
async def draw_pinball(body: PinballBody, db: DB, user: CurrentUser):
    return await service.draw_pinball(db, user, body)


@router.get("/draws")
async def history(
    db: DB,
    user: CurrentUser,
    grade: str | None = None,
    class_no: str | None = Query(None, alias="classNo"),
    type: DrawType | None = None,
    limit: str | None = None,
):
    return await service.history(db, opt_int("grade", grade), opt_int("classNo", class_no), type, opt_int("limit", limit))


@router.get("/draws/{draw_id}")
async def draw_detail(draw_id: str, db: DB, user: CurrentUser):
    return await service.draw_detail(db, draw_id)


@router.get("/draws/{draw_id}/verification")
async def verification(draw_id: str, db: DB, user: CurrentUser):
    return await service.verification(db, draw_id)
