import hashlib
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import DrawType, PinballMode, Role
from app.common.exceptions import AppException, forbidden, not_found
from app.common.ids import is_uuid, new_id
from app.common.timeutil import now_kst, to_iso
from app.core.config import settings
from app.domains.game.models import Draw
from app.domains.game.pinball import draw_winners
from app.domains.game.rng import ALGORITHM, generate_seed
from app.domains.game.schemas import PinballBody, SeatDrawBody
from app.domains.game.seat import SeatPlan, assign_seats, available_seats
from app.domains.user.models import Student, User


def _bad(code: str, message: str) -> AppException:
    return AppException(400, code, message)


async def _roster(db: AsyncSession, grade: int, class_no: int) -> list[Student]:
    if not (1 <= grade <= 3 and 1 <= class_no <= 4):
        raise not_found("CLASS_NOT_FOUND", "학급을 찾을 수 없습니다.")
    return list(
        (
            await db.scalars(
                select(Student)
                .where(Student.grade == grade, Student.class_no == class_no)
                .order_by(Student.student_number)
            )
        ).all()
    )


def _authorize(user: User, grade: int, class_no: int, own: Student | None) -> None:
    """교사·관리자, 또는 해당 학급 학생만 뽑을 수 있다."""
    if user.role in (Role.TEACHER, Role.ADMIN):
        return
    if user.role == Role.STUDENT and own is not None and (own.grade, own.class_no) == (grade, class_no):
        return
    raise forbidden()


def _hash(result) -> str:
    return hashlib.sha256(json.dumps(result, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


# ---------------- 자리뽑기 ----------------


async def _previous_seats(db: AsyncSession, grade: int, class_no: int, by_id: dict[str, Student]) -> dict[int, tuple[int, int]]:
    last = await db.scalar(
        select(Draw)
        .where(Draw.type == DrawType.SEAT, Draw.grade == grade, Draw.class_no == class_no)
        .order_by(Draw.created_at.desc(), Draw.draw_id)
        .limit(1)
    )
    if last is None:
        return {}
    return {a["number"]: (a["row"], a["col"]) for a in last.result["assignments"]}


async def draw_seats(db: AsyncSession, user: User, body: SeatDrawBody) -> dict:
    roster = await _roster(db, body.grade, body.class_no)
    _authorize(user, body.grade, body.class_no, await db.get(Student, user.user_id))
    by_id = {s.student_id: s for s in roster}
    lay = body.layout

    disabled = {(p.row, p.col) for p in lay.disabled_seats}
    if any(not (1 <= r <= lay.rows and 1 <= c <= lay.cols) for r, c in disabled):
        raise _bad("FIXED_SEAT_CONFLICT", "사용하지 않는 자리가 배치 범위를 벗어났습니다.")

    for sid in [*body.excluded_student_ids, *(f.student_id for f in body.fixed_seats)]:
        if sid not in by_id:
            raise _bad("STUDENT_NOT_IN_CLASS", "학급 명단에 없는 학생입니다.")
    excluded = set(body.excluded_student_ids)

    fixed: dict[int, tuple[int, int]] = {}
    seen_seats: set[tuple[int, int]] = set()
    for f in body.fixed_seats:
        seat = (f.row, f.col)
        number = by_id[f.student_id].student_number
        if (
            not (1 <= f.row <= lay.rows and 1 <= f.col <= lay.cols)
            or seat in disabled
            or seat in seen_seats
            or number in fixed
            or f.student_id in excluded
        ):
            raise _bad("FIXED_SEAT_CONFLICT", "고정 자리가 범위 밖이거나 사용하지 않는 자리이거나 중복됩니다.")
        seen_seats.add(seat)
        fixed[number] = seat

    targets = [s for s in roster if s.student_id not in excluded]
    plan = SeatPlan(lay.rows, lay.cols, disabled, [s.student_number for s in targets], fixed)
    if len(targets) > len(available_seats(plan)):
        raise _bad("NOT_ENOUGH_SEATS", "사용 가능한 자리가 학생 수보다 적습니다.")

    by_number = {s.student_number: s for s in roster}
    if body.avoid_previous_seat:
        plan.avoid_previous = True
        plan.previous = await _previous_seats(db, body.grade, body.class_no, by_id)

    seed = generate_seed()
    outcome = assign_seats(seed, plan)
    result = {
        "assignments": [
            {
                "row": r,
                "col": c,
                "studentId": by_number[n].student_id,
                "number": n,
                "name": by_number[n].user.name,
                "fixed": is_fixed,
            }
            for r, c, n, is_fixed in outcome.placements
        ],
        "emptySeats": [{"row": r, "col": c} for r, c in outcome.empty],
        "warnings": outcome.warnings,
    }
    options = {
        "candidates": sorted(plan.students),
        "layout": {
            "rows": lay.rows,
            "cols": lay.cols,
            "groupShape": lay.group_shape,
            "disabledSeats": [{"row": r, "col": c} for r, c in sorted(disabled)],
        },
        "fixedSeats": [{"number": n, "row": r, "col": c} for n, (r, c) in sorted(fixed.items())],
        "avoidPreviousSeat": plan.avoid_previous,
        "previousSeats": [{"number": n, "row": r, "col": c} for n, (r, c) in sorted(plan.previous.items())]
        if plan.avoid_previous
        else [],
    }
    draw = Draw(
        draw_id=new_id(),
        type=DrawType.SEAT,
        grade=body.grade,
        class_no=body.class_no,
        seed=seed,
        options=options,
        result=result,
        created_by=user.user_id,
        created_at=now_kst(),
    )
    db.add(draw)
    await db.commit()
    return _draw_out(draw)


# ---------------- 핀볼 ----------------


async def _previous_winners(db: AsyncSession, draw_id: str | None) -> set[int]:
    """previousDrawId부터 이어진 연속 추첨에서 이미 뽑힌 번호."""
    winners: set[int] = set()
    seen: set[str] = set()
    while draw_id and draw_id not in seen:
        seen.add(draw_id)
        prev = await db.get(Draw, draw_id)
        if prev is None:
            break
        winners.update(w["number"] for w in prev.result["winners"])
        draw_id = prev.previous_draw_id
    return winners


async def draw_pinball(db: AsyncSession, user: User, body: PinballBody) -> dict:
    roster = await _roster(db, body.grade, body.class_no)
    _authorize(user, body.grade, body.class_no, await db.get(Student, user.user_id))
    by_id = {s.student_id: s for s in roster}
    for sid in body.excluded_student_ids:
        if sid not in by_id:
            raise _bad("STUDENT_NOT_IN_CLASS", "학급 명단에 없는 학생입니다.")

    previous = None
    if body.previous_draw_id is not None:
        previous = await db.get(Draw, body.previous_draw_id) if is_uuid(body.previous_draw_id) else None
        if previous is None or previous.type != DrawType.PINBALL or (previous.grade, previous.class_no) != (
            body.grade,
            body.class_no,
        ):
            raise _bad("INVALID_PREVIOUS_DRAW", "이어갈 수 없는 이전 추첨입니다.")

    excluded_numbers = {by_id[i].student_number for i in body.excluded_student_ids}
    already = set() if body.allow_duplicate else await _previous_winners(db, body.previous_draw_id)
    candidates = sorted(s.student_number for s in roster if s.student_number not in excluded_numbers | already)
    if len(candidates) < body.winner_count:
        raise _bad("NOT_ENOUGH_CANDIDATES", "추첨 대상이 당첨 인원보다 적습니다.")

    seed = generate_seed()
    numbers = draw_winners(seed, candidates, body.winner_count)
    by_number = {s.student_number: s for s in roster}
    draw = Draw(
        draw_id=new_id(),
        type=DrawType.PINBALL,
        mode=body.mode,
        grade=body.grade,
        class_no=body.class_no,
        seed=seed,
        options={
            "candidates": candidates,
            "mode": body.mode.value,
            "winnerCount": body.winner_count,
            "allowDuplicate": body.allow_duplicate,
        },
        result={
            "winners": [
                {"order": i, "studentId": by_number[n].student_id, "number": n, "name": by_number[n].user.name}
                for i, n in enumerate(numbers, start=1)
            ]
        },
        previous_draw_id=previous.draw_id if previous else None,
        created_by=user.user_id,
        created_at=now_kst(),
    )
    db.add(draw)
    await db.commit()
    return _draw_out(draw)


# ---------------- 조회·검증 ----------------


def _draw_out(d: Draw) -> dict:
    base = {
        "drawId": d.draw_id,
        "type": d.type.value,
        "grade": d.grade,
        "classNo": d.class_no,
        "seed": d.seed,
        "createdAt": to_iso(d.created_at),
    }
    if d.type == DrawType.SEAT:
        return {
            **base,
            "assignments": d.result["assignments"],
            "emptySeats": d.result["emptySeats"],
            "warnings": d.result["warnings"],
        }
    return {
        **base,
        "mode": d.mode.value if d.mode else None,
        "candidateCount": len(d.options["candidates"]),
        "winners": d.result["winners"],
    }


async def get_draw(db: AsyncSession, draw_id: str) -> Draw:
    draw = await db.get(Draw, draw_id) if is_uuid(draw_id) else None
    if draw is None:
        raise not_found("DRAW_NOT_FOUND", "추첨 결과를 찾을 수 없습니다.")
    return draw


async def draw_detail(db: AsyncSession, draw_id: str) -> dict:
    return _draw_out(await get_draw(db, draw_id))


def _public_result(d: Draw) -> list:
    """검증용 결과. 이름 없이 번호만."""
    if d.type == DrawType.SEAT:
        return [[a["row"], a["col"], a["number"]] for a in d.result["assignments"]]
    return [w["number"] for w in sorted(d.result["winners"], key=lambda w: w["order"])]


async def verification(db: AsyncSession, draw_id: str) -> dict:
    d = await get_draw(db, draw_id)
    result = _public_result(d)
    options = {k: v for k, v in d.options.items() if k != "candidates"}
    return {
        "drawId": d.draw_id,
        "seed": d.seed,
        "algorithm": ALGORITHM,
        "input": {"candidates": d.options["candidates"], "options": options},
        "result": result,
        "resultHash": _hash(result),
    }


def replay(draw_type: DrawType, seed: str, candidates: list[int], options: dict) -> list:
    """저장된 입력과 시드로 결과를 다시 계산한다. 검증 응답의 result와 같아야 한다."""
    if draw_type == DrawType.PINBALL:
        return draw_winners(seed, candidates, options["winnerCount"])
    lay = options["layout"]
    plan = SeatPlan(
        lay["rows"],
        lay["cols"],
        {(s["row"], s["col"]) for s in lay["disabledSeats"]},
        candidates,
        {f["number"]: (f["row"], f["col"]) for f in options["fixedSeats"]},
        options["avoidPreviousSeat"],
        {p["number"]: (p["row"], p["col"]) for p in options["previousSeats"]},
    )
    return [[r, c, n] for r, c, n, _ in assign_seats(seed, plan).placements]


async def history(
    db: AsyncSession, grade: int | None, class_no: int | None, type_: DrawType | None, limit: int | None
) -> dict:
    limit = settings.draw_history_default if limit is None else max(1, min(limit, settings.draw_history_max))
    stmt = select(Draw, User.name).join(User, User.user_id == Draw.created_by)
    if grade is not None:
        stmt = stmt.where(Draw.grade == grade)
    if class_no is not None:
        stmt = stmt.where(Draw.class_no == class_no)
    if type_ is not None:
        stmt = stmt.where(Draw.type == type_)
    rows = (await db.execute(stmt.order_by(Draw.created_at.desc(), Draw.draw_id).limit(limit))).all()
    items = []
    for d, creator in rows:
        if d.type == DrawType.SEAT:
            summary = f"배치 인원 {len(d.result['assignments'])}명"
        else:
            summary = "당첨자: " + ", ".join(w["name"] for w in d.result["winners"])
        items.append(
            {
                "drawId": d.draw_id,
                "type": d.type.value,
                "mode": d.mode.value if d.mode else None,
                "grade": d.grade,
                "classNo": d.class_no,
                "createdBy": creator,
                "createdAt": to_iso(d.created_at),
                "summary": summary,
            }
        )
    return {"items": items}


__all__ = ["PinballMode"]
