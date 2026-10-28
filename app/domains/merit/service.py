import math

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import SCORE_COLUMNS, SCORE_LABELS, Role, ScoreType
from app.common.exceptions import not_found
from app.common.ids import is_uuid
from app.common.pagination import make_page, offset
from app.common.params import opt_int
from app.common.timeutil import to_iso
from app.core.config import settings
from app.domains.merit import repository as repo
from app.domains.merit.models import Evidence, MeisterGradeCriteria, MeisterScoreDetail, MeisterScoreItem
from app.domains.user.models import Student, User


def _is_teacher(user: User) -> bool:
    return user.role in (Role.TEACHER, Role.ADMIN)


def parse_page(value: str | None) -> int:
    """숫자가 아니거나 1 미만이면 1페이지로 취급한다."""
    try:
        page = int(value) if value is not None else 1
    except ValueError:
        return 1
    return page if page >= 1 else 1


async def rankings(db: AsyncSession, user: User, grade_raw: str | None, page_raw: str | None) -> dict:
    grade = opt_int("grade", grade_raw, 1, 3)
    size = settings.ranking_page_size
    total = await repo.count_students(db, grade)
    total_pages = math.ceil(total / size)
    page = parse_page(page_raw)
    if page > max(total_pages, 1):
        page = 1  # 마지막 페이지를 넘으면 1페이지 데이터를 돌려준다

    rows = await repo.ranking_rows(db, grade, page, size) if total else []
    items = [
        {
            "rank": r.ranking,
            "studentId": r.student_id,
            "name": r.name,
            "grade": r.grade,
            "classNo": r.class_no,
            "number": r.student_number,
            "totalScore": r.total_score,
            "isMe": r.student_id == user.user_id,
        }
        for r in rows
    ]

    my_rank = None
    if user.role == Role.STUDENT:
        mine = await repo.rank_of(db, user.user_id, grade)
        if mine is not None:
            position = await repo.position_of(db, mine, grade)
            my_rank = {
                "studentId": mine.student_id,
                "rank": mine.ranking,
                "totalScore": mine.total_score,
                "page": math.ceil(position / size),
            }

    return {"grade": grade, **make_page(items, page, size, total), "myRank": my_rank}


async def get_student_or_404(db: AsyncSession, student_id: str) -> Student:
    student = await db.get(Student, student_id) if is_uuid(student_id) else None
    if student is None:
        raise not_found("STUDENT_NOT_FOUND", "학생을 찾을 수 없습니다.")
    return student


async def student_detail(db: AsyncSession, user: User, student_id: str) -> dict:
    s = await get_student_or_404(db, student_id)
    mine = await repo.rank_of(db, s.student_id, None)
    return {
        "studentId": s.student_id,
        "name": s.user.name,
        "grade": s.grade,
        "classNo": s.class_no,
        "number": s.student_number,
        "totalScore": s.total_score,
        "rank": mine.ranking if mine else None,
        "githubUrl": s.github_url,
        "linkedinUrl": s.linkedin_url,
        "isMe": s.student_id == user.user_id,
    }


def grade_for(raw: int, grades: list[dict]) -> str | None:
    for g in sorted(grades, key=lambda g: g["minRawScore"], reverse=True):
        if raw >= g["minRawScore"]:
            return g["grade"]
    return None


async def meister_scores(db: AsyncSession, student_id: str) -> dict:
    s = await get_student_or_404(db, student_id)
    criteria = {c.score_type: c for c in (await db.scalars(select(MeisterGradeCriteria))).all()}
    counts = dict(
        (
            await db.execute(
                select(MeisterScoreDetail.score_type, func.count())
                .where(MeisterScoreDetail.student_id == student_id)
                .group_by(MeisterScoreDetail.score_type)
            )
        ).all()
    )
    # 평가항목별 획득 점수. 점수가 없는 항목도 0점으로 내려준다
    earned = dict(
        (
            await db.execute(
                select(MeisterScoreDetail.item_id, func.sum(MeisterScoreDetail.points))
                .where(MeisterScoreDetail.student_id == student_id, MeisterScoreDetail.item_id.is_not(None))
                .group_by(MeisterScoreDetail.item_id)
            )
        ).all()
    )
    items_by_type: dict[ScoreType, list[dict]] = {}
    for item in (await db.scalars(select(MeisterScoreItem).order_by(MeisterScoreItem.item_id))).all():
        items_by_type.setdefault(item.score_type, []).append(
            {
                "itemId": item.item_id,
                "name": item.name,
                "maxPoints": item.max_points,
                "earnedPoints": int(earned.get(item.item_id, 0) or 0),
            }
        )
    areas = []
    for st in ScoreType:  # 점수가 없어도 5개 영역을 모두 반환한다
        raw = getattr(s, SCORE_COLUMNS[st])
        c = criteria.get(st)
        areas.append(
            {
                "scoreType": st.value,
                "label": SCORE_LABELS[st],
                "rawScore": raw,
                "convertedScore": round(raw * c.conversion_rate, 2) if c else None,
                "grade": grade_for(raw, c.grades) if c else None,
                "detailCount": counts.get(st, 0),
                "items": items_by_type.get(st, []),
            }
        )
    return {
        "studentId": s.student_id,
        "totalScore": s.total_score,
        "criteriaRegistered": bool(criteria),
        "areas": areas,
    }


async def score_history(
    db: AsyncSession,
    user: User,
    student_id: str,
    score_type: ScoreType | None,
    order: str,
    page: int,
) -> dict:
    await get_student_or_404(db, student_id)
    can_see_evidence = _is_teacher(user) or user.user_id == student_id
    d = MeisterScoreDetail
    base = select(d).where(d.student_id == student_id)
    if score_type is not None:
        base = base.where(d.score_type == score_type)
    total = (await db.scalar(select(func.count()).select_from(base.subquery()))) or 0

    teacher = User.__table__.alias("teacher_u")
    stmt = (
        select(d, teacher.c.name, MeisterScoreItem.name, Evidence.file_name)
        .join(teacher, teacher.c.user_id == d.teacher_id)
        .outerjoin(MeisterScoreItem, MeisterScoreItem.item_id == d.item_id)
        .outerjoin(Evidence, Evidence.evidence_id == d.evidence_id)
        .where(d.student_id == student_id)
    )
    if score_type is not None:
        stmt = stmt.where(d.score_type == score_type)
    stmt = stmt.order_by(d.created_at.asc() if order == "asc" else d.created_at.desc(), d.meister_point_id)
    rows = (await db.execute(stmt.limit(settings.default_page_size).offset(offset(page, settings.default_page_size)))).all()

    items = []
    for detail, teacher_name, item_name, file_name in rows:
        evidence = None
        if can_see_evidence and detail.evidence_id:
            evidence = {"evidenceId": detail.evidence_id, "fileName": file_name}
        items.append(
            {
                "detailId": detail.meister_point_id,
                "scoreType": detail.score_type.value,
                "label": SCORE_LABELS[detail.score_type],
                "itemName": item_name,
                "content": detail.content,
                "points": detail.points,
                "teacher": {"teacherId": detail.teacher_id, "name": teacher_name},
                "evidence": evidence,
                "createdAt": to_iso(detail.created_at),
            }
        )
    return make_page(items, page, settings.default_page_size, total)


async def grade_criteria(db: AsyncSession) -> dict:
    rows = (await db.scalars(select(MeisterGradeCriteria))).all()
    by_type = {c.score_type: c for c in rows}
    areas = [
        {
            "scoreType": st.value,
            "label": SCORE_LABELS[st],
            "maxRawScore": by_type[st].max_raw_score,
            "conversionRate": by_type[st].conversion_rate,
            "grades": sorted(by_type[st].grades, key=lambda g: g["minRawScore"], reverse=True),
        }
        for st in ScoreType
        if st in by_type
    ]
    return {"registered": bool(areas), "areas": areas}


async def score_items(db: AsyncSession, score_type: ScoreType | None) -> dict:
    stmt = select(MeisterScoreItem).order_by(MeisterScoreItem.item_id)
    if score_type is not None:
        stmt = stmt.where(MeisterScoreItem.score_type == score_type)
    return {
        "items": [
            {
                "itemId": i.item_id,
                "scoreType": i.score_type.value,
                "name": i.name,
                "maxPoints": i.max_points,
                "description": i.description,
            }
            for i in (await db.scalars(stmt)).all()
        ]
    }
