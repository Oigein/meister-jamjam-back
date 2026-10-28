from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from app.common.ratelimit import check_ip_limit
from app.core.config import settings
from app.core.dependencies import DB, CurrentUser, TeacherUser
from app.domains.mileage import service
from app.domains.mileage.schemas import MeritPointCreate

router = APIRouter(tags=["mileage"])


def _limit(request: Request) -> None:
    check_ip_limit(request, "point-rules", settings.rate_point_rules_per_min)


@router.get("/point-rules", dependencies=[Depends(_limit)])
async def point_rules(
    request: Request,
    db: DB,
    user: CurrentUser,
    type: str | None = None,
    category: list[str] = Query(default=[]),
    q: str | None = None,
):
    payload = await service.list_rules(db, type, category, q)
    etag = service.etag_of(payload)
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    from fastapi.responses import JSONResponse

    return JSONResponse(payload, headers=headers)


@router.get("/students/{student_id}/merit-points")
async def merit_points(
    student_id: str,
    db: DB,
    user: CurrentUser,
    group_by: Literal["none", "teacher"] = Query("none", alias="groupBy"),
):
    return await service.merit_points(db, user, student_id, group_by)


@router.post("/merit-points", status_code=201)
async def grant_merit_point(body: MeritPointCreate, db: DB, teacher: TeacherUser):
    return await service.grant(db, teacher, body)
