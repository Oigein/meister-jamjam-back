from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import Role
from app.common.exceptions import AppException, forbidden, not_found, validation_failed, field_error
from app.domains.user import repository as repo
from app.domains.user.links import LinkError, normalize_github, normalize_linkedin
from app.domains.user.models import Student, Teacher, User
from app.domains.user.schemas import ProfileUpdate

LINK_MESSAGES = {
    "INVALID_HOST": {"githubUrl": "GitHub 주소가 아닙니다.", "linkedinUrl": "LinkedIn 주소가 아닙니다."},
    "MISSING_ID": "아이디가 없는 주소입니다.",
    "INVALID_ID": "아이디 형식이 올바르지 않습니다.",
    "NOT_PERSONAL_PROFILE": "개인 프로필 주소(linkedin.com/in/아이디)를 입력하세요.",
    "RESERVED_PATH": "개인 계정 주소를 입력하세요.",
    "INVALID_SCHEME": "사용할 수 없는 주소입니다.",
}


def _link_message(reason: str, field: str) -> str:
    msg = LINK_MESSAGES[reason]
    return msg[field] if isinstance(msg, dict) else msg


async def me(db: AsyncSession, user: User) -> dict:
    student = None
    if user.role == Role.STUDENT:
        s = await repo.get_student(db, user.user_id)
        if s is not None:
            student = {"grade": s.grade, "classNo": s.class_no, "number": s.student_number}
    teacher = None
    if user.role in (Role.TEACHER, Role.ADMIN):
        # 뽑기 화면이 교사의 담임 학급을 기본값으로 채우는 데 쓴다
        t = await repo.get_teacher(db, user.user_id)
        if t is not None:
            teacher = {
                "subject": t.subject,
                "position": t.position,
                "homeroomGrade": t.homeroom_grade,
                "homeroomClass": t.homeroom_class,
            }
    return {
        "userId": user.user_id,
        "name": user.name,
        "email": user.email,
        "role": user.role.value,
        "profileImageUrl": user.profile_image_url,
        "student": student,
        "teacher": teacher,
    }


async def get_profile(db: AsyncSession, user: User) -> dict:
    s = await repo.get_student(db, user.user_id) if user.role == Role.STUDENT else None
    return {"githubUrl": s.github_url if s else None, "linkedinUrl": s.linkedin_url if s else None}


async def update_profile(db: AsyncSession, user: User, body: ProfileUpdate) -> dict:
    if user.role != Role.STUDENT:
        raise forbidden()
    student = await repo.get_student(db, user.user_id)
    if student is None:
        raise forbidden()

    fields = body.model_fields_set
    errors = []
    updates: dict[str, str | None] = {}
    for key, attr, fn in (
        ("githubUrl", "github_url", normalize_github),
        ("linkedinUrl", "linkedin_url", normalize_linkedin),
    ):
        if attr not in fields:
            continue
        try:
            updates[attr] = fn(getattr(body, attr))  # 서버가 정규화를 처음부터 다시 검사한다
        except LinkError as exc:
            errors.append(field_error(key, exc.reason, _link_message(exc.reason, key)))
    if errors:  # 하나라도 실패하면 둘 다 저장하지 않는다
        raise validation_failed(*errors)

    for attr, value in updates.items():
        setattr(student, attr, value)
    await db.commit()
    return {"githubUrl": student.github_url, "linkedinUrl": student.linkedin_url}


async def search_teachers(
    db: AsyncSession, q: str | None, subject: str | None, position: str | None
) -> dict:
    stmt = select(Teacher).join(User, User.user_id == Teacher.teacher_id)
    if q and q.strip():
        stmt = stmt.where(User.name.contains(q.strip(), autoescape=True))
    if subject and subject.strip():
        stmt = stmt.where(Teacher.subject.contains(subject.strip(), autoescape=True))
    if position and position.strip():
        stmt = stmt.where(Teacher.position.contains(position.strip(), autoescape=True))
    rows = (await db.scalars(stmt.order_by(User.name))).all()
    # 이름·과목·직책만 반환한다 (이메일 등 개인정보 제외)
    return {
        "items": [
            {"teacherId": t.teacher_id, "name": t.user.name, "subject": t.subject, "position": t.position}
            for t in rows
        ]
    }


async def class_roster(db: AsyncSession, grade: int, class_no: int) -> dict:
    if not (1 <= grade <= 3 and 1 <= class_no <= 4):
        raise not_found("CLASS_NOT_FOUND", "학급을 찾을 수 없습니다.")
    rows = (
        await db.scalars(
            select(Student)
            .where(Student.grade == grade, Student.class_no == class_no)
            .order_by(Student.student_number)
        )
    ).all()
    return {
        "grade": grade,
        "classNo": class_no,
        "students": [
            {"studentId": s.student_id, "number": s.student_number, "name": s.user.name} for s in rows
        ],
    }


__all__ = ["AppException"]
