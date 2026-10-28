from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.user.models import Student, Teacher, User


async def get_user(db: AsyncSession, user_id: str) -> User | None:
    return await db.get(User, user_id)


async def get_user_by_google_id(db: AsyncSession, google_id: str) -> User | None:
    return await db.scalar(select(User).where(User.google_id == google_id))


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == email))


async def get_student(db: AsyncSession, student_id: str) -> Student | None:
    return await db.get(Student, student_id)


async def get_teacher(db: AsyncSession, teacher_id: str) -> Teacher | None:
    return await db.get(Teacher, teacher_id)


async def get_student_by_no(db: AsyncSession, grade: int, class_no: int, number: int) -> Student | None:
    return await db.scalar(
        select(Student).where(
            Student.grade == grade, Student.class_no == class_no, Student.student_number == number
        )
    )
