from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.enums import Role
from app.common.ids import new_id
from app.core.database import Base, enum_col


class User(Base):
    __tablename__ = "Users"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    google_id: Mapped[str | None] = mapped_column(String(255), unique=True)  # 사전 등록 시점엔 NULL
    name: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    role: Mapped[Role] = mapped_column(enum_col(Role))
    profile_image_url: Mapped[str | None] = mapped_column(String(500))


class Student(Base):
    __tablename__ = "Students"
    __table_args__ = (UniqueConstraint("grade", "class_no", "student_number", name="UQ_STUDENT_NO"),)

    student_id: Mapped[str] = mapped_column(String(36), ForeignKey("Users.user_id"), primary_key=True)
    grade: Mapped[int] = mapped_column(Integer)
    class_no: Mapped[int] = mapped_column(Integer)
    student_number: Mapped[int] = mapped_column(Integer)
    job_basic_point: Mapped[int] = mapped_column(Integer, default=0)
    major_skill_point: Mapped[int] = mapped_column(Integer, default=0)
    character_job_ethic_point: Mapped[int] = mapped_column(Integer, default=0)
    humanities_literacy_point: Mapped[int] = mapped_column(Integer, default=0)
    foreign_language_point: Mapped[int] = mapped_column(Integer, default=0)
    total_merit_points: Mapped[int] = mapped_column(Integer, default=0)
    github_url: Mapped[str | None] = mapped_column(String(255))
    linkedin_url: Mapped[str | None] = mapped_column(String(255))

    user: Mapped[User] = relationship(lazy="joined")

    @property
    def total_score(self) -> int:
        return (
            self.job_basic_point
            + self.major_skill_point
            + self.character_job_ethic_point
            + self.humanities_literacy_point
            + self.foreign_language_point
        )


class Teacher(Base):
    __tablename__ = "Teachers"

    teacher_id: Mapped[str] = mapped_column(String(36), ForeignKey("Users.user_id"), primary_key=True)
    subject: Mapped[str | None] = mapped_column(String(50))
    position: Mapped[str | None] = mapped_column(String(50))
    homeroom_grade: Mapped[int | None] = mapped_column(Integer)
    homeroom_class: Mapped[int | None] = mapped_column(Integer)

    user: Mapped[User] = relationship(lazy="joined")
