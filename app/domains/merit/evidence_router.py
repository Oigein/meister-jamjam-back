from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, Response, UploadFile

from app.common.enums import EvidenceStatus, ScoreType
from app.common.params import opt_int
from app.common.ratelimit import check_user_limit
from app.core.config import settings
from app.core.dependencies import DB, CurrentUser, StudentUser, TeacherUser
from app.domains.merit import evidence_service as service
from app.domains.merit.schemas import ApproveBody, DirectGrantBody, RejectBody

router = APIRouter(tags=["merit"])


@router.post("/evidences", status_code=201)
async def submit_evidence(
    db: DB,
    user: StudentUser,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(...),
    description: str | None = Form(None),
    score_type: str | None = Form(None, alias="scoreType"),
):
    check_user_limit(user.user_id, "upload", settings.rate_upload_per_min)
    result, evidence_id = await service.submit(db, user, file, title, description, score_type)
    background.add_task(service.run_analysis, evidence_id)  # 저장 후 AI 분석은 비동기로
    return result


@router.get("/me/evidences")
async def my_evidences(
    db: DB, user: StudentUser, status: EvidenceStatus | None = None, page: int = Query(1, ge=1)
):
    return await service.my_list(db, user, status, page)


@router.get("/teacher/evidences")
async def teacher_evidences(
    db: DB,
    teacher: TeacherUser,
    status: EvidenceStatus | None = None,
    student_id: str | None = Query(None, alias="studentId"),
    page: int = Query(1, ge=1),
):
    return await service.teacher_list(db, status, student_id or None, page)


@router.get("/evidences/{evidence_id}")
async def evidence_detail(evidence_id: str, db: DB, user: CurrentUser):
    return await service.detail(db, user, evidence_id)


@router.get("/evidences/{evidence_id}/file")
async def evidence_file(evidence_id: str, db: DB, user: CurrentUser):
    data, ev = await service.read_file(db, user, evidence_id)
    return Response(
        data,
        media_type=ev.content_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(ev.file_name)}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/evidences/{evidence_id}/analysis", status_code=202)
async def reanalyze(evidence_id: str, db: DB, teacher: TeacherUser, background: BackgroundTasks):
    result = await service.reanalyze(db, evidence_id)
    background.add_task(service.run_analysis, evidence_id)
    return result


@router.post("/evidences/{evidence_id}/approve")
async def approve(evidence_id: str, body: ApproveBody, db: DB, teacher: TeacherUser):
    return await service.approve(db, teacher, evidence_id, body)


@router.post("/evidences/{evidence_id}/reject")
async def reject(evidence_id: str, body: RejectBody, db: DB, teacher: TeacherUser):
    return await service.reject(db, teacher, evidence_id, body)


@router.post("/meister-scores", status_code=201)
async def direct_grant(body: DirectGrantBody, db: DB, teacher: TeacherUser):
    return await service.direct_grant(db, teacher, body)


@router.get("/teacher/students")
async def teacher_students(
    db: DB,
    teacher: TeacherUser,
    q: str | None = None,
    grade: str | None = None,
    class_no: str | None = Query(None, alias="classNo"),
    number: str | None = None,
    page: int = Query(1, ge=1),
):
    return await service.teacher_students(
        db, q, opt_int("grade", grade), opt_int("classNo", class_no), opt_int("number", number), page
    )


@router.get("/teacher/meister-scores")
async def teacher_score_history(
    db: DB,
    teacher: TeacherUser,
    student_id: str | None = Query(None, alias="studentId"),
    teacher_id: str | None = Query(None, alias="teacherId"),
    score_type: ScoreType | None = Query(None, alias="scoreType"),
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    page: int = Query(1, ge=1),
):
    return await service.teacher_score_history(
        db, teacher, student_id or None, teacher_id or None, score_type, date_from, date_to, page
    )
