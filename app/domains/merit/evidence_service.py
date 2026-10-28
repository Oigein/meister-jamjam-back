import os
import re

from fastapi import UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import (
    SCORE_COLUMNS,
    SCORE_LABELS,
    AnalysisStatus,
    EvidenceStatus,
    NotificationType,
    ScoreType,
)
from app.common.exceptions import AppException, conflict, field_error, not_found, validation_failed
from app.common.filetype import EXTENSIONS, sniff
from app.common.ids import is_uuid, new_id
from app.common.pagination import make_page, offset
from app.common.storage import private_storage
from app.common.timeutil import now_kst, to_iso
from app.core.config import settings
from app.core.database import get_sessionmaker
from app.domains.merit.analyzer import get_analyzer
from app.domains.merit.models import Evidence, MeisterScoreDetail, MeisterScoreItem
from app.domains.merit.schemas import ApproveBody, DirectGrantBody, RejectBody
from app.domains.notification import service as notify
from app.domains.user.models import Student, User

ALLOWED_EVIDENCE_TYPES = {"image/jpeg", "image/png", "application/pdf"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _student_brief(s: Student) -> dict:
    return {
        "studentId": s.student_id,
        "name": s.user.name,
        "grade": s.grade,
        "classNo": s.class_no,
        "number": s.student_number,
    }


# ---------------- 제출·분석 ----------------


async def submit(
    db: AsyncSession,
    user: User,
    file: UploadFile,
    title: str,
    description: str | None,
    score_type_raw: str | None,
) -> tuple[dict, str]:
    title = (title or "").strip()
    errors = []
    if not 1 <= len(title) <= settings.evidence_title_max:
        errors.append(field_error("title", "LENGTH", f"제목은 1~{settings.evidence_title_max}자로 입력하세요."))
    if description is not None and len(description) > 200:
        errors.append(field_error("description", "TOO_LONG", "설명은 200자 이하로 입력하세요."))
    hint = None
    if score_type_raw:
        try:
            hint = ScoreType(score_type_raw)
        except ValueError:
            errors.append(field_error("scoreType", "INVALID_VALUE", "올바른 영역이 아닙니다."))
    if errors:
        raise validation_failed(*errors)

    student = await db.get(Student, user.user_id)
    if student is None:
        raise not_found("STUDENT_NOT_FOUND", "학생을 찾을 수 없습니다.")

    data = await file.read(settings.evidence_max_bytes + 1)
    if not data:
        raise validation_failed(field_error("file", "EMPTY", "파일을 선택하세요."))
    if len(data) > settings.evidence_max_bytes:
        raise AppException(413, "FILE_TOO_LARGE", "파일은 10MB 이하만 올릴 수 있습니다.")
    content_type = sniff(data)  # 확장자가 아니라 파일 내용으로 판별
    if content_type not in ALLOWED_EVIDENCE_TYPES:
        raise AppException(415, "UNSUPPORTED_FILE_TYPE", "JPG, PNG, PDF 파일만 올릴 수 있습니다.")

    ext = EXTENSIONS[content_type]
    file_name = os.path.basename((file.filename or "").replace("\\", "/"))[:200] or f"{title}.{ext}"
    key = await private_storage().save(data, "evidences", ext)
    ev = Evidence(
        evidence_id=new_id(),
        student_id=user.user_id,
        title=title,
        description=description or None,
        score_type_hint=hint,
        file_key=key,
        file_name=file_name,
        content_type=content_type,
        status=EvidenceStatus.PENDING,
        analysis_status=AnalysisStatus.PROCESSING,
        created_at=now_kst(),
    )
    db.add(ev)
    await db.commit()
    return (
        {
            "evidenceId": ev.evidence_id,
            "title": ev.title,
            "status": ev.status.value,
            "analysisStatus": ev.analysis_status.value,
            "createdAt": to_iso(ev.created_at),
        },
        ev.evidence_id,
    )


async def run_analysis(evidence_id: str) -> None:
    """응답 뒤에 백그라운드로 실행한다. 실패해도 증빙 제출 자체는 유지한다."""
    async with get_sessionmaker()() as db:
        ev = await db.get(Evidence, evidence_id)
        if ev is None or ev.status != EvidenceStatus.PENDING:
            return
        try:
            data = await private_storage().read(ev.file_key)
            items = (await score_items_for_ai(db))
            result = await get_analyzer().analyze(
                file_bytes=data,
                content_type=ev.content_type,
                title=ev.title,
                hint=ev.score_type_hint.value if ev.score_type_hint else None,
                items=items,
            )
            ev.ai_result = result
            ev.analysis_status = AnalysisStatus.DONE
        except Exception:
            ev.ai_result = None
            ev.analysis_status = AnalysisStatus.FAILED
        ev.analyzed_at = now_kst()
        await db.commit()


async def score_items_for_ai(db: AsyncSession) -> list[dict]:
    rows = (await db.scalars(select(MeisterScoreItem).order_by(MeisterScoreItem.item_id))).all()
    return [
        {"itemId": i.item_id, "scoreType": i.score_type.value, "name": i.name, "maxPoints": i.max_points}
        for i in rows
    ]


async def reanalyze(db: AsyncSession, evidence_id: str) -> dict:
    ev = await _get(db, evidence_id)
    if ev.status != EvidenceStatus.PENDING:
        raise conflict("EVIDENCE_ALREADY_REVIEWED", "이미 처리된 증빙자료입니다.")
    ev.analysis_status = AnalysisStatus.PROCESSING
    await db.commit()
    return {"analysisStatus": AnalysisStatus.PROCESSING.value}


# ---------------- 조회 ----------------


async def _get(db: AsyncSession, evidence_id: str) -> Evidence:
    ev = await db.get(Evidence, evidence_id) if is_uuid(evidence_id) else None
    if ev is None:
        raise not_found("EVIDENCE_NOT_FOUND", "증빙자료를 찾을 수 없습니다.")
    return ev


async def get_visible(db: AsyncSession, user: User, evidence_id: str) -> Evidence:
    """제출한 학생 본인과 교사만. 그 외에는 존재 여부를 숨기려고 404."""
    from app.common.enums import Role

    ev = await _get(db, evidence_id)
    if user.role == Role.STUDENT and ev.student_id != user.user_id:
        raise not_found("EVIDENCE_NOT_FOUND", "증빙자료를 찾을 수 없습니다.")
    return ev


async def my_list(db: AsyncSession, user: User, status: EvidenceStatus | None, page: int) -> dict:
    stmt = select(Evidence).where(Evidence.student_id == user.user_id)
    if status is not None:
        stmt = stmt.where(Evidence.status == status)
    total = (await db.scalar(select(func.count()).select_from(stmt.subquery()))) or 0
    size = settings.default_page_size
    rows = (
        await db.scalars(stmt.order_by(Evidence.created_at.desc()).limit(size).offset(offset(page, size)))
    ).all()
    items = [
        {
            "evidenceId": e.evidence_id,
            "title": e.title,
            "status": e.status.value,
            "rejectReason": e.reject_reason,
            "approvedPoints": e.approved_points,
            "createdAt": to_iso(e.created_at),
            "reviewedAt": to_iso(e.reviewed_at) if e.reviewed_at else None,
        }
        for e in rows
    ]
    return make_page(items, page, size, total)


async def teacher_list(
    db: AsyncSession, status: EvidenceStatus | None, student_id: str | None, page: int
) -> dict:
    # 기본은 검토 대기. 학생을 지정하면 상태를 따로 고르지 않는 한 그 학생의 전체 제출 내역
    if status is None and not student_id:
        status = EvidenceStatus.PENDING
    stmt = select(Evidence)
    if status is not None:
        stmt = stmt.where(Evidence.status == status)
    if student_id:
        stmt = stmt.where(Evidence.student_id == student_id)
    total = (await db.scalar(select(func.count()).select_from(stmt.subquery()))) or 0
    size = settings.default_page_size
    order = Evidence.created_at.asc() if status == EvidenceStatus.PENDING else Evidence.created_at.desc()
    rows = (await db.scalars(stmt.order_by(order).limit(size).offset(offset(page, size)))).all()
    students = {
        s.student_id: s
        for s in (await db.scalars(select(Student).where(Student.student_id.in_({e.student_id for e in rows})))).all()
    }
    items = []
    for e in rows:
        rec = (e.ai_result or {}).get("recommendation") or {}
        items.append(
            {
                "evidenceId": e.evidence_id,
                "student": _student_brief(students[e.student_id]),
                "title": e.title,
                "status": e.status.value,
                "analysisStatus": e.analysis_status.value,
                "recommendedScoreType": rec.get("scoreType"),
                "expectedPoints": rec.get("expectedPoints"),
                "createdAt": to_iso(e.created_at),
            }
        )
    return make_page(items, page, size, total)


async def detail(db: AsyncSession, user: User, evidence_id: str) -> dict:
    ev = await get_visible(db, user, evidence_id)
    student = await db.get(Student, ev.student_id)
    ai = ev.ai_result or {}
    rec = ai.get("recommendation")
    extracted = ai.get("extracted")

    duplicate = None
    if rec and rec.get("itemId") and extracted and extracted.get("name"):
        needle = _norm(extracted["name"])
        rows = (
            await db.scalars(
                select(MeisterScoreDetail)
                .where(
                    MeisterScoreDetail.student_id == ev.student_id,
                    MeisterScoreDetail.item_id == rec["itemId"],
                    MeisterScoreDetail.points > 0,
                    MeisterScoreDetail.evidence_id.is_distinct_from(ev.evidence_id),
                )
                .order_by(MeisterScoreDetail.created_at)
            )
        ).all()
        for d in rows:
            if needle and needle in _norm(d.content):
                duplicate = {"detailId": d.meister_point_id, "content": d.content, "createdAt": to_iso(d.created_at)}
                break

    review = None
    if ev.status != EvidenceStatus.PENDING:
        reviewer = await db.get(User, ev.reviewed_by) if ev.reviewed_by else None
        detail_id = await db.scalar(
            select(MeisterScoreDetail.meister_point_id).where(MeisterScoreDetail.evidence_id == ev.evidence_id)
        )
        review = {
            "teacher": {"teacherId": ev.reviewed_by, "name": reviewer.name if reviewer else None},
            "reviewedAt": to_iso(ev.reviewed_at) if ev.reviewed_at else None,
            "rejectReason": ev.reject_reason,
            "detailId": detail_id,
        }
    return {
        "evidenceId": ev.evidence_id,
        "student": _student_brief(student),
        "title": ev.title,
        "description": ev.description,
        "file": {
            "fileName": ev.file_name,
            "contentType": ev.content_type,
            "url": f"/api/evidences/{ev.evidence_id}/file",
        },
        "status": ev.status.value,
        "aiAnalysis": {
            "status": ev.analysis_status.value,
            "extracted": extracted,
            "recommendation": rec,
            "duplicateSuspect": duplicate,
            "analyzedAt": to_iso(ev.analyzed_at) if ev.analyzed_at else None,
        },
        "review": review,
        "createdAt": to_iso(ev.created_at),
    }


async def read_file(db: AsyncSession, user: User, evidence_id: str) -> tuple[bytes, Evidence]:
    ev = await get_visible(db, user, evidence_id)
    return await private_storage().read(ev.file_key), ev


# ---------------- 점수 반영 (승인·직접 부여 공통) ----------------


async def apply_score(
    db: AsyncSession,
    teacher: User,
    student_id: str,
    score_type: ScoreType,
    item_id: int,
    points: int,
    content: str,
    evidence_id: str | None = None,
) -> tuple[MeisterScoreDetail, Student]:
    """검증 → 내역 저장 → 학생 영역 점수 가산. 호출한 쪽이 같은 트랜잭션에서 커밋한다."""
    item = await db.get(MeisterScoreItem, item_id)
    if item is None:
        raise not_found("ITEM_NOT_FOUND", "평가항목을 찾을 수 없습니다.")
    if item.score_type != score_type:
        raise validation_failed(field_error("scoreType", "ITEM_MISMATCH", "평가항목의 영역과 일치하지 않습니다."))

    # 동시 요청에도 한도·0점 검사가 어긋나지 않도록 학생 행을 잠근다 (MySQL)
    student = (
        await db.execute(select(Student).where(Student.student_id == student_id).with_for_update())
    ).scalar_one_or_none()
    if student is None:
        raise not_found("STUDENT_NOT_FOUND", "학생을 찾을 수 없습니다.")

    column = SCORE_COLUMNS[score_type]
    if points > 0:
        existing = (
            await db.scalars(
                select(MeisterScoreDetail).where(
                    MeisterScoreDetail.student_id == student_id, MeisterScoreDetail.item_id == item_id
                )
            )
        ).all()
        remaining = item.max_points - sum(d.points for d in existing)
        if points > remaining:
            raise AppException(
                400,
                "EXCEEDS_MAX_POINTS",
                "최대 인정 점수를 넘었습니다.",
                extra={"remainingPoints": max(remaining, 0)},
            )
        same = next((d for d in existing if d.points > 0 and _norm(d.content) == _norm(content)), None)
        if same is not None:
            raise conflict("DUPLICATE_ACHIEVEMENT", "이미 인정된 실적입니다.", detailId=same.meister_point_id)
    elif getattr(student, column) + points < 0:
        raise AppException(400, "SCORE_BELOW_ZERO", "영역 점수가 0점 미만이 될 수 없습니다.")

    detail = MeisterScoreDetail(
        meister_point_id=new_id(),
        teacher_id=teacher.user_id,
        student_id=student_id,
        score_type=score_type,
        item_id=item_id,
        evidence_id=evidence_id,
        content=content,
        points=points,
        created_at=now_kst(),
    )
    db.add(detail)
    setattr(student, column, getattr(student, column) + points)
    await db.flush()
    return detail, student


def _score_result(detail: MeisterScoreDetail, student: Student) -> dict:
    column = SCORE_COLUMNS[detail.score_type]
    return {
        "scoreDetail": {
            "detailId": detail.meister_point_id,
            "scoreType": detail.score_type.value,
            "itemId": detail.item_id,
            "points": detail.points,
            "content": detail.content,
            "createdAt": to_iso(detail.created_at),
        },
        "studentScore": {
            "scoreType": detail.score_type.value,
            "rawScore": getattr(student, column),
            "totalScore": student.total_score,
        },
    }


async def approve(db: AsyncSession, teacher: User, evidence_id: str, body: ApproveBody) -> dict:
    ev = await _get(db, evidence_id)
    if ev.status != EvidenceStatus.PENDING:
        raise conflict("EVIDENCE_ALREADY_REVIEWED", "이미 승인 또는 반려된 증빙자료입니다.")

    detail, student = await apply_score(
        db, teacher, ev.student_id, body.score_type, body.item_id, body.points, body.content, ev.evidence_id
    )
    # 동시에 다른 교사가 처리했다면 조건부 UPDATE가 0행이라 전체를 되돌린다
    res = await db.execute(
        update(Evidence)
        .where(Evidence.evidence_id == ev.evidence_id, Evidence.status == EvidenceStatus.PENDING)
        .values(
            status=EvidenceStatus.APPROVED,
            reviewed_by=teacher.user_id,
            reviewed_at=now_kst(),
            approved_points=body.points,
        )
    )
    if res.rowcount == 0:
        raise conflict("EVIDENCE_ALREADY_REVIEWED", "이미 승인 또는 반려된 증빙자료입니다.")

    notify.add(
        db,
        ev.student_id,
        NotificationType.EVIDENCE_APPROVED,
        "증빙자료 승인",
        f"제출한 '{ev.title}'가 승인되어 {SCORE_LABELS[body.score_type]} {body.points:+d}점이 반영되었습니다.",
        f"/students/{ev.student_id}?tab=history&detailId={detail.meister_point_id}",
    )
    await notify.commit(db)
    return {"evidenceId": ev.evidence_id, "status": EvidenceStatus.APPROVED.value, **_score_result(detail, student)}


async def reject(db: AsyncSession, teacher: User, evidence_id: str, body: RejectBody) -> dict:
    ev = await _get(db, evidence_id)
    res = await db.execute(
        update(Evidence)
        .where(Evidence.evidence_id == ev.evidence_id, Evidence.status == EvidenceStatus.PENDING)
        .values(
            status=EvidenceStatus.REJECTED,
            reject_reason=body.reason,
            reviewed_by=teacher.user_id,
            reviewed_at=now_kst(),
        )
    )
    if res.rowcount == 0:
        raise conflict("EVIDENCE_ALREADY_REVIEWED", "이미 승인 또는 반려된 증빙자료입니다.")
    notify.add(
        db,
        ev.student_id,
        NotificationType.EVIDENCE_REJECTED,
        "증빙자료 반려",
        f"제출한 '{ev.title}'가 반려되었습니다. 사유: {body.reason}"[:255],
        f"/me/evidences/{ev.evidence_id}",
    )
    await notify.commit(db)
    return {"evidenceId": ev.evidence_id, "status": EvidenceStatus.REJECTED.value, "rejectReason": body.reason}


async def direct_grant(db: AsyncSession, teacher: User, body: DirectGrantBody) -> dict:
    if body.points == 0:
        raise validation_failed(field_error("points", "ZERO", "0점은 부여할 수 없습니다."))
    if not is_uuid(body.student_id):
        raise not_found("STUDENT_NOT_FOUND", "학생을 찾을 수 없습니다.")
    detail, student = await apply_score(
        db, teacher, body.student_id, body.score_type, body.item_id, body.points, body.content
    )
    notify.add(
        db,
        body.student_id,
        NotificationType.MEISTER_SCORE_CHANGED,
        "마역량 점수 변경",
        f"{SCORE_LABELS[body.score_type]} 점수가 {body.points:+d}점 변경되었습니다.",
        f"/students/{body.student_id}?tab=history&detailId={detail.meister_point_id}",
    )
    await notify.commit(db)
    return _score_result(detail, student)


# ---------------- 교사용 조회 ----------------


async def teacher_students(
    db: AsyncSession, q: str | None, grade: int | None, class_no: int | None, number: int | None, page: int
) -> dict:
    pending = (
        select(func.count())
        .select_from(Evidence)
        .where(Evidence.student_id == Student.student_id, Evidence.status == EvidenceStatus.PENDING)
        .correlate(Student)
        .scalar_subquery()
    )
    stmt = select(Student).join(User, User.user_id == Student.student_id)
    if q and q.strip():
        stmt = stmt.where(User.name.contains(q.strip(), autoescape=True))
    if grade is not None:
        stmt = stmt.where(Student.grade == grade)
    if class_no is not None:
        stmt = stmt.where(Student.class_no == class_no)
    if number is not None:
        stmt = stmt.where(Student.student_number == number)
    total = (await db.scalar(select(func.count()).select_from(stmt.subquery()))) or 0
    size = settings.default_page_size
    rows = (
        await db.execute(
            stmt.add_columns(pending.label("pending"))
            .order_by(Student.grade, Student.class_no, Student.student_number)
            .limit(size)
            .offset(offset(page, size))
        )
    ).all()
    items = [
        {**_student_brief(s), "totalScore": s.total_score, "pendingEvidenceCount": count} for s, count in rows
    ]
    return make_page(items, page, size, total)


async def teacher_score_history(
    db: AsyncSession,
    teacher: User,
    student_id: str | None,
    teacher_id: str | None,
    score_type: ScoreType | None,
    date_from,
    date_to,
    page: int,
) -> dict:
    from datetime import datetime, time, timedelta

    d = MeisterScoreDetail
    stmt = select(d)
    if student_id:
        stmt = stmt.where(d.student_id == student_id)
    if teacher_id:
        stmt = stmt.where(d.teacher_id == (teacher.user_id if teacher_id == "me" else teacher_id))
    if score_type is not None:
        stmt = stmt.where(d.score_type == score_type)
    if date_from is not None:
        stmt = stmt.where(d.created_at >= datetime.combine(date_from, time.min))
    if date_to is not None:
        stmt = stmt.where(d.created_at < datetime.combine(date_to + timedelta(days=1), time.min))
    total = (await db.scalar(select(func.count()).select_from(stmt.subquery()))) or 0
    size = settings.default_page_size
    rows = (
        await db.scalars(stmt.order_by(d.created_at.desc(), d.meister_point_id).limit(size).offset(offset(page, size)))
    ).all()
    students = {
        s.student_id: s for s in (await db.scalars(select(Student).where(Student.student_id.in_({r.student_id for r in rows})))).all()
    }
    teachers = {u.user_id: u for u in (await db.scalars(select(User).where(User.user_id.in_({r.teacher_id for r in rows})))).all()}
    items_by_id = {i.item_id: i for i in (await db.scalars(select(MeisterScoreItem))).all()}
    items = [
        {
            "detailId": r.meister_point_id,
            "student": _student_brief(students[r.student_id]),
            "scoreType": r.score_type.value,
            "label": SCORE_LABELS[r.score_type],
            "itemName": items_by_id[r.item_id].name if r.item_id in items_by_id else None,
            "points": r.points,
            "content": r.content,
            "teacher": {"teacherId": r.teacher_id, "name": teachers[r.teacher_id].name},
            "evidenceId": r.evidence_id,
            "createdAt": to_iso(r.created_at),
        }
        for r in rows
    ]
    return make_page(items, page, size, total)
