from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.user.models import Student, User

TOTAL = (
    Student.job_basic_point
    + Student.major_skill_point
    + Student.character_job_ethic_point
    + Student.humanities_literacy_point
    + Student.foreign_language_point
)


def _scope(stmt, grade: int | None):
    return stmt.where(Student.grade == grade) if grade is not None else stmt


def _ranked(grade: int | None):
    """RANK()는 선택한 범위(전체 또는 학년) 안에서 따로 계산한다. 동점이면 같은 순위, 다음은 건너뜀."""
    stmt = select(
        Student.student_id,
        User.name,
        Student.grade,
        Student.class_no,
        Student.student_number,
        TOTAL.label("total_score"),
        func.rank().over(order_by=TOTAL.desc()).label("ranking"),
    ).join(User, User.user_id == Student.student_id)
    return _scope(stmt, grade).subquery()


async def count_students(db: AsyncSession, grade: int | None) -> int:
    return (await db.scalar(_scope(select(func.count()).select_from(Student), grade))) or 0


async def ranking_rows(db: AsyncSession, grade: int | None, page: int, size: int):
    r = _ranked(grade)
    stmt = (
        select(r)
        .order_by(r.c.total_score.desc(), r.c.grade, r.c.class_no, r.c.student_number)
        .limit(size)
        .offset((page - 1) * size)
    )
    return (await db.execute(stmt)).all()


async def rank_of(db: AsyncSession, student_id: str, grade: int | None):
    r = _ranked(grade)
    return (await db.execute(select(r).where(r.c.student_id == student_id))).first()


async def position_of(db: AsyncSession, row, grade: int | None) -> int:
    """정렬(총점 ↓, 학년, 반, 번호) 기준으로 몇 번째 줄인지 (1부터)."""
    before = or_(
        TOTAL > row.total_score,
        and_(
            TOTAL == row.total_score,
            or_(
                Student.grade < row.grade,
                and_(
                    Student.grade == row.grade,
                    or_(
                        Student.class_no < row.class_no,
                        and_(Student.class_no == row.class_no, Student.student_number < row.student_number),
                    ),
                ),
            ),
        ),
    )
    count = await db.scalar(_scope(select(func.count()).select_from(Student).where(before), grade))
    return (count or 0) + 1
