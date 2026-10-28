from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import DrawType, PinballMode
from app.common.ids import new_id
from app.common.timeutil import now_kst
from app.core.database import Base, enum_col


class Draw(Base):
    __tablename__ = "Draws"

    draw_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    type: Mapped[DrawType] = mapped_column(enum_col(DrawType))
    mode: Mapped[PinballMode | None] = mapped_column(enum_col(PinballMode))
    grade: Mapped[int] = mapped_column(Integer)
    class_no: Mapped[int] = mapped_column(Integer)
    seed: Mapped[str] = mapped_column(String(64))
    options: Mapped[dict] = mapped_column(JSON)  # 학생 번호 기준 입력값
    result: Mapped[dict] = mapped_column(JSON)  # 학생 스냅샷 포함 결과
    previous_draw_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("Draws.draw_id"))
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("Users.user_id"))
    created_at: Mapped[datetime] = mapped_column(default=now_kst, index=True)
