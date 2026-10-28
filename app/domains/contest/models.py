from datetime import date, datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import ContestScope, ScheduleType
from app.common.timeutil import now_kst
from app.core.database import Base, enum_col


class ContestCategory(Base):
    __tablename__ = "ContestCategories"

    category_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(20))
    normalized_name: Mapped[str] = mapped_column(String(40), unique=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("Users.user_id"))
    created_at: Mapped[datetime] = mapped_column(default=now_kst)


class ContestTag(Base):
    __tablename__ = "ContestTags"

    tag_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tag_name: Mapped[str] = mapped_column(String(10), unique=True)


class Contest(Base):
    __tablename__ = "Contests"

    contest_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    author: Mapped[str] = mapped_column(String(36), ForeignKey("Users.user_id"))
    contest_name: Mapped[str] = mapped_column(String(30))
    content: Mapped[str] = mapped_column(Text)
    scope: Mapped[ContestScope] = mapped_column(enum_col(ContestScope))
    category_id: Mapped[int] = mapped_column(Integer, ForeignKey("ContestCategories.category_id"))
    start_at: Mapped[datetime]
    finish_at: Mapped[datetime]
    expected_score: Mapped[int | None] = mapped_column(Integer)
    difficulty: Mapped[int | None] = mapped_column(Integer)
    prep_hours: Mapped[int | None] = mapped_column(Integer)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)


class ContestTagging(Base):
    __tablename__ = "ContestTaggings"

    contest_id: Mapped[int] = mapped_column(Integer, ForeignKey("Contests.contest_id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(Integer, ForeignKey("ContestTags.tag_id"), primary_key=True)


class ContestBookmark(Base):
    __tablename__ = "ContestBookmarks"

    student_id: Mapped[str] = mapped_column(String(36), ForeignKey("Students.student_id"), primary_key=True)
    contest_id: Mapped[int] = mapped_column(Integer, ForeignKey("Contests.contest_id"), primary_key=True)


class AcademicSchedule(Base):
    __tablename__ = "AcademicSchedules"

    schedule_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[ScheduleType] = mapped_column(enum_col(ScheduleType))
    title: Mapped[str] = mapped_column(String(100))
    start_date: Mapped[date]
    end_date: Mapped[date]
