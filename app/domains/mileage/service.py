import hashlib
import json

from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import PointType, Role
from app.common.exceptions import field_error, forbidden, not_found, validation_failed
from app.common.ids import is_uuid
from app.common.timeutil import to_iso
from app.domains.mileage.models import MeritPointDetail, PointRule
from app.domains.mileage.schemas import MeritPointCreate
from app.domains.user.models import Student, User


# ---- 상벌점 기준 ----


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_rules(db: AsyncSession, type_raw: str | None, categories: list[str], q: str | None) -> dict:
    base = select(PointRule).where(PointRule.is_active.is_(True))
    all_categories = (
        await db.scalars(
            select(PointRule.category).where(PointRule.is_active.is_(True)).distinct().order_by(PointRule.category)
        )
    ).all()

    stmt = base
    if type_raw in (PointType.MERIT.value, PointType.DEMERIT.value):  # 허용되지 않은 값은 무시하고 전체 조회
        stmt = stmt.where(PointRule.type == PointType(type_raw))
    cats = [c for c in categories if c]
    if cats:
        stmt = stmt.where(PointRule.category.in_(cats))
    if q is not None and q.strip():
        needle = _like_escape(q.strip()[:50])
        stmt = stmt.where(
            PointRule.title.like(f"%{needle}%", escape="\\") | PointRule.description.like(f"%{needle}%", escape="\\")
        )
    stmt = stmt.order_by(
        case((PointRule.type == PointType.MERIT, 0), else_=1),
        PointRule.category,
        PointRule.points.desc(),
        PointRule.rule_id,
    )
    rules = (await db.scalars(stmt)).all()
    return {
        "total": len(rules),
        "categories": list(all_categories),  # 필터와 관계없이 항상 전체 분류
        "items": [
            {
                "ruleId": r.rule_id,
                "type": r.type.value,
                "category": r.category,
                "title": r.title,
                "points": r.points,
                "description": r.description,
                "note": r.note,
            }
            for r in rules
        ],
    }


def etag_of(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    return f'"{hashlib.sha256(raw).hexdigest()[:32]}"'


# ---- 상·벌점 내역 ----


def _item(d: MeritPointDetail, teacher_name: str) -> dict:
    return {
        "meritPointId": d.merit_point_id,
        "type": (PointType.MERIT if d.points > 0 else PointType.DEMERIT).value,
        "title": d.title,
        "content": d.content,
        "points": abs(d.points),  # 항상 양수, 구분은 type·merits/demerits로
        "teacher": {"teacherId": d.teacher_id, "name": teacher_name},
        "createdAt": to_iso(d.created_at),
    }


async def merit_points(db: AsyncSession, user: User, student_id: str, group_by: str) -> dict:
    is_teacher = user.role in (Role.TEACHER, Role.ADMIN)
    if not is_teacher and user.user_id != student_id:
        raise forbidden()  # 다른 학생의 상·벌점은 볼 수 없다
    if not is_uuid(student_id) or await db.get(Student, student_id) is None:
        raise not_found("STUDENT_NOT_FOUND", "학생을 찾을 수 없습니다.")

    rows = (
        await db.execute(
            select(MeritPointDetail, User.name)
            .join(User, User.user_id == MeritPointDetail.teacher_id)
            .where(MeritPointDetail.student_id == student_id)
            .order_by(MeritPointDetail.created_at.desc(), MeritPointDetail.merit_point_id)
        )
    ).all()

    def totals(details) -> tuple[int, int]:
        merit = sum(d.points for d in details if d.points > 0)
        demerit = -sum(d.points for d in details if d.points < 0)
        return merit, demerit

    merit_total, demerit_total = totals([d for d, _ in rows])
    head = {
        "studentId": student_id,
        "meritTotal": merit_total,
        "demeritTotal": demerit_total,
        "net": merit_total - demerit_total,
    }
    if group_by == "teacher":
        groups: dict[str, dict] = {}
        for d, name in rows:
            g = groups.setdefault(d.teacher_id, {"teacher": {"teacherId": d.teacher_id, "name": name}, "rows": []})
            g["rows"].append(d)
        by_teacher = []
        for g in groups.values():
            m, dm = totals(g["rows"])
            by_teacher.append(
                {
                    "teacher": g["teacher"],
                    "meritTotal": m,
                    "demeritTotal": dm,
                    "items": [
                        {k: v for k, v in _item(d, g["teacher"]["name"]).items() if k != "teacher"}
                        for d in g["rows"]
                    ],
                }
            )
        return {**head, "byTeacher": by_teacher}
    return {
        **head,
        "merits": [_item(d, n) for d, n in rows if d.points > 0],
        "demerits": [_item(d, n) for d, n in rows if d.points < 0],
    }


async def grant(db: AsyncSession, teacher: User, body: MeritPointCreate) -> dict:
    student = await db.get(Student, body.student_id) if is_uuid(body.student_id) else None
    if student is None:
        raise not_found("STUDENT_NOT_FOUND", "학생을 찾을 수 없습니다.")
    if body.rule_id is not None:
        rule = await db.get(PointRule, body.rule_id)
        if rule is None:
            raise not_found("RULE_NOT_FOUND", "상벌점 기준을 찾을 수 없습니다.")
        if rule.type != body.type:
            raise validation_failed(field_error("ruleId", "TYPE_MISMATCH", "기준의 구분과 일치하지 않습니다."))

    signed = body.points if body.type == PointType.MERIT else -body.points  # 벌점은 음수로 기록
    detail = MeritPointDetail(
        teacher_id=teacher.user_id,
        student_id=student.student_id,
        rule_id=body.rule_id,
        title=body.title,
        content=body.content,
        points=signed,
    )
    db.add(detail)
    await db.execute(
        update(Student)
        .where(Student.student_id == student.student_id)
        .values(total_merit_points=Student.total_merit_points + signed)
    )
    await db.commit()
    return _item(detail, teacher.name)
