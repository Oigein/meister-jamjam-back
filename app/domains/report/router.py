from urllib.parse import quote

from fastapi import APIRouter, File, Query, Response, UploadFile

from app.common.enums import SelfReportStatus
from app.common.ratelimit import check_user_limit
from app.core.config import settings
from app.core.dependencies import DB, CurrentUser, StudentUser, TeacherUser
from app.domains.report import service
from app.domains.report.schemas import ReplyBody, SelfReportCreate, SelfReportUpdate, StatusBody

router = APIRouter(tags=["report"])


# 고정 경로를 {report_id}보다 먼저 선언한다
@router.get("/self-reports/default-recipient")
async def default_recipient(db: DB, user: StudentUser):
    return await service.default_recipient(db, user)


@router.post("/self-reports/attachments", status_code=201)
async def upload_attachment(db: DB, user: StudentUser, file: UploadFile = File(...)):
    check_user_limit(user.user_id, "upload", settings.rate_upload_per_min)
    return await service.upload_attachment(db, user, file)


@router.post("/self-reports", status_code=201)
async def create_report(body: SelfReportCreate, db: DB, user: StudentUser):
    return await service.create(db, user, body)


@router.get("/me/self-reports")
async def my_reports(db: DB, user: StudentUser, status: SelfReportStatus | None = None, page: int = Query(1, ge=1)):
    return await service.my_reports(db, user, status, page)


@router.get("/teacher/self-reports")
async def received_reports(db: DB, teacher: TeacherUser, status: SelfReportStatus | None = None, page: int = Query(1, ge=1)):
    return await service.received_reports(db, teacher, status, page)


@router.get("/self-reports/{report_id}")
async def report_detail(report_id: str, db: DB, user: CurrentUser):
    return await service.get_detail(db, user, report_id)


@router.patch("/self-reports/{report_id}")
async def update_report(report_id: str, body: SelfReportUpdate, db: DB, user: StudentUser):
    return await service.edit(db, user, report_id, body)


@router.delete("/self-reports/{report_id}", status_code=204)
async def withdraw_report(report_id: str, db: DB, user: StudentUser):
    await service.withdraw(db, user, report_id)
    return Response(status_code=204)


@router.patch("/self-reports/{report_id}/status")
async def change_status(report_id: str, body: StatusBody, db: DB, teacher: TeacherUser):
    return await service.change_status(db, teacher, report_id, body.status)


@router.get("/self-reports/{report_id}/replies")
async def list_replies(report_id: str, db: DB, user: CurrentUser):
    return await service.list_replies(db, user, report_id)


@router.post("/self-reports/{report_id}/replies", status_code=201)
async def add_reply(report_id: str, body: ReplyBody, db: DB, user: CurrentUser):
    return await service.add_reply(db, user, report_id, body)


@router.get("/self-reports/{report_id}/attachments/{attachment_id}")
async def download_attachment(report_id: str, attachment_id: str, db: DB, user: CurrentUser):
    data, content_type, name = await service.download_attachment(db, user, report_id, attachment_id)
    return Response(
        data,
        media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
