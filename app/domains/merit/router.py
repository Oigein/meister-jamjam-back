from typing import Literal

from fastapi import APIRouter, Query

from app.common.enums import ScoreType
from app.core.dependencies import DB, CurrentUser
from app.domains.merit import service
from app.domains.merit.evidence_router import router as evidence_router

router = APIRouter(tags=["merit"])
router.include_router(evidence_router)


@router.get("/meister/rankings")
async def rankings(db: DB, user: CurrentUser, grade: str | None = None, page: str | None = None):
    return await service.rankings(db, user, grade, page)


@router.get("/meister/grade-criteria")
async def grade_criteria(db: DB, user: CurrentUser):
    return await service.grade_criteria(db)


@router.get("/meister/score-items")
async def score_items(db: DB, user: CurrentUser, score_type: ScoreType | None = Query(None, alias="scoreType")):
    return await service.score_items(db, score_type)


@router.get("/students/{student_id}")
async def student_detail(student_id: str, db: DB, user: CurrentUser):
    return await service.student_detail(db, user, student_id)


@router.get("/students/{student_id}/meister-scores")
async def meister_scores(student_id: str, db: DB, user: CurrentUser):
    return await service.meister_scores(db, student_id)


@router.get("/students/{student_id}/meister-scores/history")
async def score_history(
    student_id: str,
    db: DB,
    user: CurrentUser,
    score_type: ScoreType | None = Query(None, alias="scoreType"),
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1),
):
    return await service.score_history(db, user, student_id, score_type, order, page)
