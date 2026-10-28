import re
from datetime import date, datetime

from sqlalchemy import and_, case, delete, func, null, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import ContestScope, Role
from app.common.exceptions import field_error, forbidden, not_found, validation_failed
from app.common.pagination import make_page, offset
from app.common.timeutil import now_kst, to_iso, today_kst
from app.core.config import settings
from app.domains.contest.models import (
    AcademicSchedule,
    Contest,
    ContestBookmark,
    ContestCategory,
    ContestTag,
    ContestTagging,
)
from app.domains.contest.schemas import ContestWrite
from app.domains.user.models import Student, User

CATEGORY_PATTERN = re.compile(r"^[0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ \-·&()]+$")
CATEGORY_MAX = 20


def _not_found() -> Exception:
    return not_found("CONTEST_NOT_FOUND", "대회를 찾을 수 없습니다.")


def _is_teacher(user: User) -> bool:
    return user.role in (Role.TEACHER, Role.ADMIN)


# ---------------- 카테고리 ----------------


def normalize_category(name: str) -> str:
    return re.sub(r"\s+", "", name).lower()


def _category_out(c: ContestCategory) -> dict:
    return {"categoryId": c.category_id, "name": c.name, "isDefault": c.is_default}


async def list_categories(db: AsyncSession) -> dict:
    rows = (
        await db.scalars(
            select(ContestCategory).order_by(
                case((ContestCategory.is_default.is_(True), 0), else_=1),
                case((ContestCategory.is_default.is_(True), ContestCategory.category_id), else_=0),
                ContestCategory.name,
            )
        )
    ).all()
    return {"items": [_category_out(c) for c in rows]}


async def add_category(db: AsyncSession, user: User, raw_name: str) -> tuple[int, dict]:
    name = (raw_name or "").strip()
    if not name:
        raise validation_failed(field_error("name", "EMPTY", "카테고리 이름을 입력하세요."))
    if len(name) > CATEGORY_MAX:
        raise validation_failed(field_error("name", "TOO_LONG", f"{CATEGORY_MAX}자 이하로 입력하세요."))
    if not CATEGORY_PATTERN.match(name):
        raise validation_failed(
            field_error("name", "INVALID_CHARACTER", "한글, 영문, 숫자, 공백, - · & ( )만 사용할 수 있습니다.")
        )
    normalized = normalize_category(name)

    async def existing() -> ContestCategory | None:
        return await db.scalar(select(ContestCategory).where(ContestCategory.normalized_name == normalized))

    found = await existing()
    if found is not None:
        return 200, {**_category_out(found), "created": False}
    category = ContestCategory(name=name, normalized_name=normalized, is_default=False, created_by=user.user_id)
    db.add(category)
    try:
        await db.commit()
    except IntegrityError:  # 동시 요청으로 UNIQUE 충돌 → 기존 행을 다시 읽어 200
        await db.rollback()
        found = await existing()
        assert found is not None
        return 200, {**_category_out(found), "created": False}
    return 201, {**_category_out(category), "created": True}


# ---------------- 대회 ----------------


async def _tags_by_contest(db: AsyncSession, contest_ids: list[int]) -> dict[int, list[str]]:
    if not contest_ids:
        return {}
    rows = (
        await db.execute(
            select(ContestTagging.contest_id, ContestTag.tag_name)
            .join(ContestTag, ContestTag.tag_id == ContestTagging.tag_id)
            .where(ContestTagging.contest_id.in_(contest_ids))
            .order_by(ContestTag.tag_id)
        )
    ).all()
    out: dict[int, list[str]] = {}
    for cid, name in rows:
        out.setdefault(cid, []).append(name)
    return out


async def _bookmarked(db: AsyncSession, user: User, contest_ids: list[int]) -> set[int]:
    if user.role != Role.STUDENT or not contest_ids:
        return set()
    rows = await db.scalars(
        select(ContestBookmark.contest_id).where(
            ContestBookmark.student_id == user.user_id, ContestBookmark.contest_id.in_(contest_ids)
        )
    )
    return set(rows.all())


def _d_day(c: Contest) -> int:
    return (c.finish_at.date() - today_kst()).days


def _list_item(c: Contest, category: ContestCategory, tags: list[str], bookmarked: bool) -> dict:
    return {
        "contestId": c.contest_id,
        "contestName": c.contest_name,
        "scope": c.scope.value,
        "category": {"categoryId": category.category_id, "name": category.name},
        "tags": tags,
        "startAt": to_iso(c.start_at),
        "finishAt": to_iso(c.finish_at),
        "dDay": _d_day(c),
        "isBookmarked": bookmarked,
    }


def _ordering():
    """마감이 가까운 순. 종료된 대회는 뒤로 (그중에서는 최근에 끝난 순)."""
    ended = Contest.finish_at < now_kst()
    return (
        case((ended, 1), else_=0),
        case((ended, null()), else_=Contest.finish_at),
        Contest.finish_at.desc(),
        Contest.contest_id,
    )


async def _list(db: AsyncSession, user: User, stmt, page: int) -> dict:
    total = (await db.scalar(select(func.count()).select_from(stmt.subquery()))) or 0
    size = settings.default_page_size
    rows = (
        await db.execute(
            stmt.join(ContestCategory, ContestCategory.category_id == Contest.category_id)
            .add_columns(ContestCategory)
            .order_by(*_ordering())
            .limit(size)
            .offset(offset(page, size))
        )
    ).all()
    ids = [c.contest_id for c, _ in rows]
    tags, marks = await _tags_by_contest(db, ids), await _bookmarked(db, user, ids)
    items = [_list_item(c, cat, tags.get(c.contest_id, []), c.contest_id in marks) for c, cat in rows]
    return make_page(items, page, size, total)


async def list_contests(
    db: AsyncSession, user: User, scope: ContestScope | None, category_id: int | None, page: int
) -> dict:
    if category_id is not None and await db.get(ContestCategory, category_id) is None:
        raise validation_failed(field_error("categoryId", "NOT_FOUND", "없는 카테고리입니다."))
    stmt = select(Contest)
    if scope is not None:
        stmt = stmt.where(Contest.scope == scope)
    if category_id is not None:
        stmt = stmt.where(Contest.category_id == category_id)
    return await _list(db, user, stmt, page)


async def my_bookmarks(db: AsyncSession, user: User, page: int) -> dict:
    stmt = select(Contest).join(ContestBookmark, ContestBookmark.contest_id == Contest.contest_id).where(
        ContestBookmark.student_id == user.user_id
    )
    return await _list(db, user, stmt, page)


async def _get(db: AsyncSession, contest_id: int) -> Contest:
    contest = await db.get(Contest, contest_id)
    if contest is None:
        raise _not_found()
    return contest


async def detail(db: AsyncSession, user: User, contest_id: int) -> dict:
    c = await _get(db, contest_id)
    category = await db.get(ContestCategory, c.category_id)
    tags = (await _tags_by_contest(db, [c.contest_id])).get(c.contest_id, [])
    marked = c.contest_id in await _bookmarked(db, user, [c.contest_id])
    author = await db.get(User, c.author)
    return {
        **_list_item(c, category, tags, marked),
        "content": c.content,
        "author": {"userId": c.author, "name": author.name if author else None},
        "expectedScore": c.expected_score,
        "difficulty": c.difficulty,
        "prepHours": c.prep_hours,
        "isVerified": c.is_verified,
    }


async def _validate_write(db: AsyncSession, body: ContestWrite) -> list[int]:
    errors = []
    if body.start_at > body.finish_at:
        errors.append(field_error("finishAt", "BEFORE_START", "종료 일시는 시작 일시 이후여야 합니다."))
    if await db.get(ContestCategory, body.category_id) is None:
        errors.append(field_error("categoryId", "NOT_FOUND", "없는 카테고리입니다."))
    tag_ids = sorted(set(body.tag_ids))
    if tag_ids:
        found = set((await db.scalars(select(ContestTag.tag_id).where(ContestTag.tag_id.in_(tag_ids)))).all())
        if found != set(tag_ids):
            errors.append(field_error("tagIds", "NOT_FOUND", "없는 태그가 포함되어 있습니다."))
    if errors:
        raise validation_failed(*errors)
    return tag_ids


async def _set_tags(db: AsyncSession, contest_id: int, tag_ids: list[int]) -> None:
    await db.execute(delete(ContestTagging).where(ContestTagging.contest_id == contest_id))
    db.add_all(ContestTagging(contest_id=contest_id, tag_id=t) for t in tag_ids)


def _apply(c: Contest, body: ContestWrite) -> None:
    c.contest_name = body.contest_name
    c.content = body.content
    c.scope = body.scope
    c.category_id = body.category_id
    c.start_at = body.start_at
    c.finish_at = body.finish_at
    if "expected_score" in body.model_fields_set:
        c.expected_score = body.expected_score
    if "difficulty" in body.model_fields_set:
        c.difficulty = body.difficulty
    if "prep_hours" in body.model_fields_set:
        c.prep_hours = body.prep_hours
    if body.is_verified is not None:
        c.is_verified = body.is_verified


async def create(db: AsyncSession, user: User, body: ContestWrite) -> dict:
    tag_ids = await _validate_write(db, body)
    contest = Contest(author=user.user_id, is_verified=False)
    _apply(contest, body)
    db.add(contest)
    await db.flush()
    await _set_tags(db, contest.contest_id, tag_ids)
    await db.commit()
    return await detail(db, user, contest.contest_id)


async def update(db: AsyncSession, user: User, contest_id: int, body: ContestWrite) -> dict:
    contest = await _get(db, contest_id)
    if user.role != Role.ADMIN and contest.author != user.user_id:
        raise forbidden("작성한 교사 또는 관리자만 수정할 수 있습니다.")
    tag_ids = await _validate_write(db, body)
    _apply(contest, body)
    await _set_tags(db, contest.contest_id, tag_ids)
    await db.commit()
    return await detail(db, user, contest_id)


async def delete_contest(db: AsyncSession, user: User, contest_id: int) -> None:
    contest = await _get(db, contest_id)
    if user.role != Role.ADMIN and contest.author != user.user_id:
        raise forbidden("작성한 교사 또는 관리자만 삭제할 수 있습니다.")
    # 하나의 트랜잭션으로 연관 행까지 삭제
    await db.execute(delete(ContestBookmark).where(ContestBookmark.contest_id == contest_id))
    await db.execute(delete(ContestTagging).where(ContestTagging.contest_id == contest_id))
    await db.delete(contest)
    await db.commit()


# ---------------- 북마크 ----------------


async def add_bookmark(db: AsyncSession, user: User, contest_id: int) -> None:
    await _get(db, contest_id)
    if await db.get(Student, user.user_id) is None:
        raise forbidden()
    if await db.get(ContestBookmark, (user.user_id, contest_id)) is not None:
        return  # 이미 있어도 204
    db.add(ContestBookmark(student_id=user.user_id, contest_id=contest_id))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()


async def remove_bookmark(db: AsyncSession, user: User, contest_id: int) -> None:
    await _get(db, contest_id)
    await db.execute(
        delete(ContestBookmark).where(
            and_(ContestBookmark.student_id == user.user_id, ContestBookmark.contest_id == contest_id)
        )
    )
    await db.commit()


# ---------------- 학사 일정 ----------------


async def schedules(db: AsyncSession, date_from: date | None, date_to: date | None) -> dict:
    stmt = select(AcademicSchedule).order_by(AcademicSchedule.start_date, AcademicSchedule.schedule_id)
    if date_from is not None:
        stmt = stmt.where(AcademicSchedule.end_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(AcademicSchedule.start_date <= date_to)
    return {
        "items": [
            {
                "scheduleId": s.schedule_id,
                "type": s.type.value,
                "title": s.title,
                "startDate": s.start_date.isoformat(),
                "endDate": s.end_date.isoformat(),
            }
            for s in (await db.scalars(stmt)).all()
        ]
    }


__all__ = ["datetime"]
