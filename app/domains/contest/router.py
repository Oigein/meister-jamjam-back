from datetime import date

from fastapi import APIRouter, Query, Response
from fastapi.responses import JSONResponse

from app.common.enums import ContestScope
from app.core.dependencies import DB, CurrentUser, StudentUser, TeacherUser
from app.domains.contest import service
from app.domains.contest.schemas import CategoryCreate, ContestWrite

router = APIRouter(tags=["contest"])


@router.get("/contest-categories")
async def list_categories(db: DB, user: CurrentUser):
    return await service.list_categories(db)


@router.post("/contest-categories")
async def add_category(body: CategoryCreate, db: DB, teacher: TeacherUser):
    status, payload = await service.add_category(db, teacher, body.name)
    return JSONResponse(payload, status_code=status)


@router.get("/contests")
async def list_contests(
    db: DB,
    user: CurrentUser,
    scope: ContestScope | None = None,
    category_id: int | None = Query(None, alias="categoryId"),
    page: int = Query(1, ge=1),
):
    return await service.list_contests(db, user, scope, category_id, page)


@router.post("/contests", status_code=201)
async def create_contest(body: ContestWrite, db: DB, teacher: TeacherUser, response: Response):
    result = await service.create(db, teacher, body)
    response.headers["Location"] = f"/api/contests/{result['contestId']}"
    return result


@router.get("/contests/{contest_id}")
async def contest_detail(contest_id: int, db: DB, user: CurrentUser):
    return await service.detail(db, user, contest_id)


@router.put("/contests/{contest_id}")
async def update_contest(contest_id: int, body: ContestWrite, db: DB, teacher: TeacherUser):
    return await service.update(db, teacher, contest_id, body)


@router.delete("/contests/{contest_id}", status_code=204)
async def delete_contest(contest_id: int, db: DB, teacher: TeacherUser):
    await service.delete_contest(db, teacher, contest_id)
    return Response(status_code=204)


@router.put("/contests/{contest_id}/bookmark", status_code=204)
async def add_bookmark(contest_id: int, db: DB, user: StudentUser):
    await service.add_bookmark(db, user, contest_id)
    return Response(status_code=204)


@router.delete("/contests/{contest_id}/bookmark", status_code=204)
async def remove_bookmark(contest_id: int, db: DB, user: StudentUser):
    await service.remove_bookmark(db, user, contest_id)
    return Response(status_code=204)


@router.get("/me/bookmarks")
async def my_bookmarks(db: DB, user: StudentUser, page: int = Query(1, ge=1)):
    return await service.my_bookmarks(db, user, page)


@router.get("/academic-schedules")
async def academic_schedules(
    db: DB,
    user: CurrentUser,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
):
    return await service.schedules(db, date_from, date_to)
