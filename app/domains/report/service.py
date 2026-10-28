import os
from datetime import timedelta

from fastapi import UploadFile
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import (
    NotificationType,
    Role,
    SelfReportStatus,
)
from app.common.exceptions import AppException, conflict, field_error, not_found, validation_failed
from app.common.filetype import EXTENSIONS, sniff
from app.common.ids import is_uuid, new_id
from app.common.mailer import get_mailer
from app.common.pagination import make_page, offset
from app.common.storage import private_storage
from app.common.timeutil import now_kst, to_iso
from app.core.config import settings
from app.core.crypto import decrypt_bytes, decrypt_text, encrypt_bytes, encrypt_text
from app.domains.notification import service as notify
from app.domains.report.models import (
    SelfReport,
    SelfReportAttachment,
    SelfReportRecipient,
    SelfReportReply,
)
from app.domains.report.schemas import ReplyBody, SelfReportCreate, SelfReportUpdate
from app.domains.user.models import Student, Teacher, User

ATTACHMENT_TYPES = {"image/jpeg", "image/png", "application/pdf"}
ALLOWED_TRANSITIONS = {
    (SelfReportStatus.READ, SelfReportStatus.IN_PROGRESS),
    (SelfReportStatus.READ, SelfReportStatus.DONE),
    (SelfReportStatus.IN_PROGRESS, SelfReportStatus.DONE),
}
STATUS_TEXT = {
    SelfReportStatus.READ: "자진 신고를 선생님이 확인했습니다.",
    SelfReportStatus.IN_PROGRESS: "자진 신고를 선생님이 처리 중입니다.",
    SelfReportStatus.DONE: "자진 신고 처리가 완료되었습니다.",
}


def _hidden() -> AppException:
    """작성자와 수신 교사 외에는 존재 여부도 알 수 없게 404."""
    return not_found("REPORT_NOT_FOUND", "신고를 찾을 수 없습니다.")


# ---------------- 접근 제어 ----------------


async def _load(db: AsyncSession, user: User, report_id: str) -> tuple[SelfReport, str]:
    """(신고, 'author'|'recipient'). 관계없는 사용자(관리자 포함)는 404."""
    report = await db.get(SelfReport, report_id) if is_uuid(report_id) else None
    if report is None:
        raise _hidden()
    if user.role == Role.STUDENT and report.student_id == user.user_id:
        return report, "author"
    if user.role in (Role.TEACHER, Role.ADMIN):
        recipient = await db.get(SelfReportRecipient, (report_id, user.user_id))
        if recipient is not None:
            return report, "recipient"
    raise _hidden()


async def _recipient_ids(db: AsyncSession, report_id: str) -> list[str]:
    return list((await db.scalars(select(SelfReportRecipient.teacher_id).where(SelfReportRecipient.report_id == report_id))).all())


# ---------------- 기본 수신자·첨부 ----------------


def _teacher_out(t: Teacher, position: str | None = None) -> dict:
    return {"teacherId": t.teacher_id, "name": t.user.name, "subject": t.subject, "position": position or t.position}


async def default_recipient(db: AsyncSession, user: User) -> dict:
    student = await db.get(Student, user.user_id)
    if student is None:
        raise not_found("STUDENT_NOT_FOUND", "학생을 찾을 수 없습니다.")
    homeroom = await db.scalar(
        select(Teacher)
        .where(Teacher.homeroom_grade == student.grade, Teacher.homeroom_class == student.class_no)
        .order_by(Teacher.teacher_id)
    )
    if homeroom is not None:
        label = homeroom.position or f"{student.grade}학년 {student.class_no}반 담임"
        return {"teacher": _teacher_out(homeroom, label), "isFallback": False, "fallbackReason": None}
    # 담임이 없으면 학년 부장 → 상담교사 순으로 대체
    for keyword in (f"{student.grade}학년 부장", "상담"):
        fallback = await db.scalar(select(Teacher).where(Teacher.position.contains(keyword, autoescape=True)).order_by(Teacher.teacher_id))
        if fallback is not None:
            return {"teacher": _teacher_out(fallback), "isFallback": True, "fallbackReason": "HOMEROOM_NOT_ASSIGNED"}
    return {"teacher": None, "isFallback": True, "fallbackReason": "HOMEROOM_NOT_ASSIGNED"}


async def upload_attachment(db: AsyncSession, user: User, file: UploadFile) -> dict:
    data = await file.read(settings.self_report_attachment_bytes + 1)
    if not data:
        raise validation_failed(field_error("file", "EMPTY", "파일을 선택하세요."))
    if len(data) > settings.self_report_attachment_bytes:
        raise AppException(413, "FILE_TOO_LARGE", "파일은 10MB 이하만 올릴 수 있습니다.")
    content_type = sniff(data)
    if content_type not in ATTACHMENT_TYPES:
        raise AppException(415, "UNSUPPORTED_FILE_TYPE", "JPG, PNG, PDF 파일만 올릴 수 있습니다.")
    name = os.path.basename((file.filename or "").replace("\\", "/"))[:200] or f"attachment.{EXTENSIONS[content_type]}"
    key = await private_storage().save(encrypt_bytes(data), "self-reports", "bin")  # 암호화해 저장
    att = SelfReportAttachment(
        attachment_id=new_id(),
        uploader_id=user.user_id,
        file_name=encrypt_text(name),
        content_type=content_type,
        file_key=key,
        size_bytes=len(data),
        created_at=now_kst(),
    )
    db.add(att)
    await db.commit()
    return {"attachmentId": att.attachment_id, "fileName": name, "sizeBytes": att.size_bytes}


async def cleanup_orphan_attachments(db: AsyncSession) -> int:
    """신고에 연결되지 않은 채 24시간이 지난 첨부를 삭제한다."""
    cutoff = now_kst() - timedelta(hours=settings.self_report_orphan_hours)
    rows = (
        await db.scalars(
            select(SelfReportAttachment).where(SelfReportAttachment.report_id.is_(None), SelfReportAttachment.created_at < cutoff)
        )
    ).all()
    for att in rows:
        await private_storage().delete(att.file_key)
        await db.delete(att)
    await db.commit()
    return len(rows)


# ---------------- 검증 ----------------


async def _check_recipients(db: AsyncSession, ids: list[str]) -> None:
    if len(set(ids)) != len(ids):
        raise validation_failed(field_error("recipientIds", "DUPLICATE", "같은 교사를 두 번 고를 수 없습니다."))
    if len(ids) > settings.self_report_max_recipients:
        raise AppException(400, "TOO_MANY_RECIPIENTS", f"수신 교사는 최대 {settings.self_report_max_recipients}명입니다.")
    found = set(
        (await db.scalars(select(Teacher.teacher_id).where(Teacher.teacher_id.in_([i for i in ids if is_uuid(i)])))).all()
    )
    if found != set(ids):
        raise AppException(400, "INVALID_RECIPIENT", "교사가 아닌 사용자는 수신자로 고를 수 없습니다.")


async def _check_attachments(db: AsyncSession, user: User, ids: list[str], report_id: str | None) -> list[SelfReportAttachment]:
    if len(set(ids)) != len(ids):
        raise validation_failed(field_error("attachmentIds", "DUPLICATE", "같은 파일이 중복되었습니다."))
    rows = []
    for aid in ids:
        att = await db.get(SelfReportAttachment, aid) if is_uuid(aid) else None
        if att is None or att.uploader_id != user.user_id or att.report_id not in (None, report_id):
            raise validation_failed(field_error("attachmentIds", "INVALID_ATTACHMENT", "사용할 수 없는 첨부파일입니다."))
        rows.append(att)
    return rows


# ---------------- 응답 만들기 ----------------


async def _student_brief(db: AsyncSession, student_id: str) -> dict:
    s = await db.get(Student, student_id)
    return {"studentId": s.student_id, "name": s.user.name, "grade": s.grade, "classNo": s.class_no, "number": s.student_number}


async def _detail(db: AsyncSession, report: SelfReport, viewer: User) -> dict:
    recipients = (
        await db.execute(
            select(SelfReportRecipient, User.name)
            .join(User, User.user_id == SelfReportRecipient.teacher_id)
            .where(SelfReportRecipient.report_id == report.report_id)
            .order_by(User.name)
        )
    ).all()
    attachments = (
        await db.scalars(
            select(SelfReportAttachment)
            .where(SelfReportAttachment.report_id == report.report_id)
            .order_by(SelfReportAttachment.created_at, SelfReportAttachment.attachment_id)
        )
    ).all()
    return {
        "reportId": report.report_id,
        "student": await _student_brief(db, report.student_id),
        "type": report.type.value,
        "title": decrypt_text(report.title),
        "content": decrypt_text(report.content),
        "recipients": [
            {"teacherId": r.teacher_id, "name": name, "readAt": to_iso(r.read_at) if r.read_at else None}
            for r, name in recipients
        ],
        "changeReason": report.change_reason.value if report.change_reason else None,
        "preferredHandling": report.preferred_handling.value,
        "attachments": [
            {"attachmentId": a.attachment_id, "fileName": decrypt_text(a.file_name), "sizeBytes": a.size_bytes}
            for a in attachments
        ],
        "status": report.status.value,
        "editable": viewer.user_id == report.student_id and report.status == SelfReportStatus.UNREAD,
        "createdAt": to_iso(report.created_at),
        "updatedAt": to_iso(report.updated_at),
    }


# ---------------- 제출·수정·철회 ----------------


async def create(db: AsyncSession, user: User, body: SelfReportCreate) -> dict:
    student = await db.get(Student, user.user_id)
    if student is None:
        raise not_found("STUDENT_NOT_FOUND", "학생을 찾을 수 없습니다.")
    await _check_recipients(db, body.recipient_ids)
    attachments = await _check_attachments(db, user, body.attachment_ids, None)

    report = SelfReport(
        report_id=new_id(),
        student_id=user.user_id,
        type=body.type,
        title=encrypt_text(body.title),
        content=encrypt_text(body.content),
        preferred_handling=body.preferred_handling,
        status=SelfReportStatus.UNREAD,
        change_reason=body.change_reason,
        created_at=now_kst(),
        updated_at=now_kst(),
    )
    db.add(report)
    await db.flush()
    for tid in body.recipient_ids:
        db.add(SelfReportRecipient(report_id=report.report_id, teacher_id=tid))
    for att in attachments:
        att.report_id = report.report_id

    # 알림·이메일에는 제목·내용을 넣지 않는다 (기기 푸시 미리보기 노출 방지)
    text = f"[자진 신고] {student.grade}학년 {student.class_no}반 {user.name} 학생으로부터 자진 신고가 접수되었습니다."
    for tid in body.recipient_ids:
        notify.add(
            db, tid, NotificationType.SELF_REPORT_RECEIVED, "자진 신고 접수", text, f"/teacher/self-reports/{report.report_id}"
        )
    await notify.commit(db)

    emails = (await db.scalars(select(User.email).where(User.user_id.in_(body.recipient_ids)))).all()
    for email in emails:
        try:
            await get_mailer().send(email, "[자진 신고] 새 신고가 접수되었습니다", text)
        except Exception:  # 메일 실패가 제출을 막지 않는다
            pass
    return await _detail(db, report, user)


async def edit(db: AsyncSession, user: User, report_id: str, body: SelfReportUpdate) -> dict:
    report, role = await _load(db, user, report_id)
    if role != "author":
        raise _hidden()
    if report.status != SelfReportStatus.UNREAD:
        raise conflict("REPORT_ALREADY_READ", "선생님이 이미 확인해 수정·삭제할 수 없습니다.")

    fields = body.model_fields_set
    if "recipient_ids" in fields and body.recipient_ids is not None:
        await _check_recipients(db, body.recipient_ids)
    attachments = None
    if "attachment_ids" in fields and body.attachment_ids is not None:
        attachments = await _check_attachments(db, user, body.attachment_ids, report_id)

    values: dict = {"updated_at": now_kst()}
    if body.type is not None:
        values["type"] = body.type
    if body.title is not None:
        values["title"] = encrypt_text(body.title)
    if body.content is not None:
        values["content"] = encrypt_text(body.content)
    if body.preferred_handling is not None:
        values["preferred_handling"] = body.preferred_handling
    if "change_reason" in fields:
        values["change_reason"] = body.change_reason

    # 상태 확인과 수정을 한 번에 처리한다. 교사가 동시에 열었다면 0행이라 409
    res = await db.execute(
        update_stmt(report_id, SelfReportStatus.UNREAD).values(**values)
    )
    if res.rowcount == 0:
        raise conflict("REPORT_ALREADY_READ", "선생님이 이미 확인해 수정·삭제할 수 없습니다.")

    if "recipient_ids" in fields and body.recipient_ids is not None:
        await db.execute(delete(SelfReportRecipient).where(SelfReportRecipient.report_id == report_id))
        for tid in body.recipient_ids:
            db.add(SelfReportRecipient(report_id=report_id, teacher_id=tid))
    removed_keys: list[str] = []
    if attachments is not None:
        keep = {a.attachment_id for a in attachments}
        current = (await db.scalars(select(SelfReportAttachment).where(SelfReportAttachment.report_id == report_id))).all()
        for old in current:
            if old.attachment_id not in keep:
                removed_keys.append(old.file_key)
                await db.delete(old)
        for att in attachments:
            att.report_id = report_id
    await db.commit()
    for key in removed_keys:
        await private_storage().delete(key)
    await db.refresh(report)
    return await _detail(db, report, user)


def update_stmt(report_id: str, status: SelfReportStatus):
    return update(SelfReport).where(SelfReport.report_id == report_id, SelfReport.status == status)


async def withdraw(db: AsyncSession, user: User, report_id: str) -> None:
    report, role = await _load(db, user, report_id)
    if role != "author":
        raise _hidden()
    res = await db.execute(update_stmt(report_id, SelfReportStatus.UNREAD).values(updated_at=now_kst()))
    if res.rowcount == 0:
        raise conflict("REPORT_ALREADY_READ", "선생님이 이미 확인해 수정·삭제할 수 없습니다.")
    keys = list((await db.scalars(select(SelfReportAttachment.file_key).where(SelfReportAttachment.report_id == report_id))).all())
    await db.execute(delete(SelfReportReply).where(SelfReportReply.report_id == report_id))
    await db.execute(delete(SelfReportAttachment).where(SelfReportAttachment.report_id == report_id))
    await db.execute(delete(SelfReportRecipient).where(SelfReportRecipient.report_id == report_id))
    # 수신 교사의 알림도 함께 제거
    from app.domains.notification.models import Notification

    await db.execute(delete(Notification).where(Notification.target_url == f"/teacher/self-reports/{report_id}"))
    await db.execute(delete(SelfReport).where(SelfReport.report_id == report_id))
    await db.commit()
    for key in keys:
        await private_storage().delete(key)


# ---------------- 조회 ----------------


async def _has_new_reply(db: AsyncSession, report_ids: list[str], viewer_id: str) -> set[str]:
    if not report_ids:
        return set()
    rows = await db.scalars(
        select(SelfReportReply.report_id)
        .where(
            SelfReportReply.report_id.in_(report_ids),
            SelfReportReply.author_id != viewer_id,
            SelfReportReply.is_read.is_(False),
        )
        .distinct()
    )
    return set(rows.all())


async def my_reports(db: AsyncSession, user: User, status: SelfReportStatus | None, page: int) -> dict:
    stmt = select(SelfReport).where(SelfReport.student_id == user.user_id)
    if status is not None:
        stmt = stmt.where(SelfReport.status == status)
    total = (await db.scalar(select(func.count()).select_from(stmt.subquery()))) or 0
    size = settings.default_page_size
    rows = (await db.scalars(stmt.order_by(SelfReport.created_at.desc()).limit(size).offset(offset(page, size)))).all()
    ids = [r.report_id for r in rows]
    new = await _has_new_reply(db, ids, user.user_id)
    names: dict[str, list[str]] = {}
    for rid, name in (
        await db.execute(
            select(SelfReportRecipient.report_id, User.name)
            .join(User, User.user_id == SelfReportRecipient.teacher_id)
            .where(SelfReportRecipient.report_id.in_(ids))
            .order_by(User.name)
        )
    ).all() if ids else []:
        names.setdefault(rid, []).append(name)
    items = [
        {
            "reportId": r.report_id,
            "type": r.type.value,
            "title": decrypt_text(r.title),
            "status": r.status.value,
            "recipients": names.get(r.report_id, []),
            "hasNewReply": r.report_id in new,
            "createdAt": to_iso(r.created_at),
        }
        for r in rows
    ]
    return make_page(items, page, size, total)


async def received_reports(db: AsyncSession, teacher: User, status: SelfReportStatus | None, page: int) -> dict:
    stmt = (
        select(SelfReport)
        .join(SelfReportRecipient, SelfReportRecipient.report_id == SelfReport.report_id)
        .where(SelfReportRecipient.teacher_id == teacher.user_id)
    )
    if status is not None:
        stmt = stmt.where(SelfReport.status == status)
    total = (await db.scalar(select(func.count()).select_from(stmt.subquery()))) or 0
    size = settings.default_page_size
    rows = (
        await db.scalars(
            stmt.order_by(case((SelfReport.status == SelfReportStatus.UNREAD, 0), else_=1), SelfReport.created_at.desc())
            .limit(size)
            .offset(offset(page, size))
        )
    ).all()
    new = await _has_new_reply(db, [r.report_id for r in rows], teacher.user_id)
    items = [
        {
            "reportId": r.report_id,
            "student": await _student_brief(db, r.student_id),
            "type": r.type.value,
            "title": decrypt_text(r.title),
            "status": r.status.value,
            "preferredHandling": r.preferred_handling.value,
            "hasNewReply": r.report_id in new,
            "createdAt": to_iso(r.created_at),
        }
        for r in rows
    ]
    return make_page(items, page, size, total)


async def _set_status(db: AsyncSession, report: SelfReport, current: SelfReportStatus, new: SelfReportStatus) -> bool:
    res = await db.execute(update_stmt(report.report_id, current).values(status=new, updated_at=now_kst()))
    if res.rowcount == 0:
        return False
    report.status = new
    notify.add(
        db,
        report.student_id,
        NotificationType.SELF_REPORT_STATUS_CHANGED,
        "자진 신고 상태 변경",
        STATUS_TEXT[new],
        f"/me/self-reports/{report.report_id}",
    )
    return True


async def get_detail(db: AsyncSession, user: User, report_id: str) -> dict:
    report, role = await _load(db, user, report_id)
    if role == "recipient":
        recipient = await db.get(SelfReportRecipient, (report_id, user.user_id))
        if recipient.read_at is None:
            recipient.read_at = now_kst()
        if report.status == SelfReportStatus.UNREAD:  # 한 명이라도 열면 READ
            await _set_status(db, report, SelfReportStatus.UNREAD, SelfReportStatus.READ)
        await notify.commit(db)
        await db.refresh(report)
    return await _detail(db, report, user)


async def change_status(db: AsyncSession, user: User, report_id: str, new: SelfReportStatus) -> dict:
    report, role = await _load(db, user, report_id)
    if role != "recipient":
        raise _hidden()
    current = report.status
    if (current, new) not in ALLOWED_TRANSITIONS or not await _set_status(db, report, current, new):
        raise conflict("INVALID_STATUS_TRANSITION", "변경할 수 없는 상태입니다.")
    await notify.commit(db)
    await db.refresh(report)
    return await _detail(db, report, user)


# ---------------- 답변 ----------------


def _reply_out(reply: SelfReportReply, author: User) -> dict:
    return {
        "replyId": reply.reply_id,
        "author": {"userId": author.user_id, "name": author.name, "role": author.role.value},
        "content": decrypt_text(reply.content),
        "createdAt": to_iso(reply.created_at),
    }


async def list_replies(db: AsyncSession, user: User, report_id: str) -> dict:
    await _load(db, user, report_id)
    rows = (
        await db.execute(
            select(SelfReportReply, User)
            .join(User, User.user_id == SelfReportReply.author_id)
            .where(SelfReportReply.report_id == report_id)
            .order_by(SelfReportReply.created_at, SelfReportReply.reply_id)
        )
    ).all()
    await db.execute(
        update(SelfReportReply)
        .where(
            SelfReportReply.report_id == report_id,
            SelfReportReply.author_id != user.user_id,
            SelfReportReply.is_read.is_(False),
        )
        .values(is_read=True)
    )
    await db.commit()
    return {"items": [_reply_out(r, a) for r, a in rows]}


async def add_reply(db: AsyncSession, user: User, report_id: str, body: ReplyBody) -> dict:
    report, role = await _load(db, user, report_id)
    if report.status == SelfReportStatus.DONE:
        raise conflict("REPORT_CLOSED", "처리가 완료된 신고에는 답변할 수 없습니다.")
    reply = SelfReportReply(
        reply_id=new_id(), report_id=report_id, author_id=user.user_id, content=encrypt_text(body.content), created_at=now_kst()
    )
    db.add(reply)

    if role == "recipient":
        recipient = await db.get(SelfReportRecipient, (report_id, user.user_id))
        if recipient.read_at is None:
            recipient.read_at = now_kst()
        # 교사가 처음 답변하면 확인 완료 → 처리 중으로 자동 변경
        if report.status == SelfReportStatus.UNREAD:
            await _set_status(db, report, SelfReportStatus.UNREAD, SelfReportStatus.READ)
            report.status = SelfReportStatus.READ
        if report.status == SelfReportStatus.READ:
            await _set_status(db, report, SelfReportStatus.READ, SelfReportStatus.IN_PROGRESS)
        targets = [(report.student_id, f"/me/self-reports/{report_id}")]
    else:
        targets = [(tid, f"/teacher/self-reports/{report_id}") for tid in await _recipient_ids(db, report_id)]
    for uid, url in targets:  # 답변 내용은 알림에 넣지 않는다
        notify.add(db, uid, NotificationType.SELF_REPORT_REPLIED, "자진 신고 답변", "자진 신고에 새 답변이 있습니다.", url)
    await notify.commit(db)
    return _reply_out(reply, user)


# ---------------- 첨부 다운로드 ----------------


async def download_attachment(db: AsyncSession, user: User, report_id: str, attachment_id: str) -> tuple[bytes, str, str]:
    await _load(db, user, report_id)  # 다운로드할 때도 권한을 다시 확인한다
    att = await db.get(SelfReportAttachment, attachment_id) if is_uuid(attachment_id) else None
    if att is None or att.report_id != report_id:
        raise _hidden()
    data = decrypt_bytes(await private_storage().read(att.file_key))
    return data, att.content_type, decrypt_text(att.file_name)
