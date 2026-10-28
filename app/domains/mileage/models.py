from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import PointType
from app.common.ids import new_id
from app.common.timeutil import now_kst
from app.core.database import Base, enum_col


class PointRule(Base):
    __tablename__ = "PointRules"

    rule_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[PointType] = mapped_column(enum_col(PointType))
    category: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(50))
    points: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class MeritPointDetail(Base):
    __tablename__ = "MeritPointDetails"

    merit_point_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    teacher_id: Mapped[str] = mapped_column(String(36), ForeignKey("Users.user_id"))
    student_id: Mapped[str] = mapped_column(String(36), ForeignKey("Students.student_id"), index=True)
    rule_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("PointRules.rule_id"))
    title: Mapped[str] = mapped_column(String(20))
    content: Mapped[str | None] = mapped_column(String(50))
    points: Mapped[int] = mapped_column(Integer)  # 상점 +, 벌점 −
    created_at: Mapped[datetime] = mapped_column(default=now_kst)
