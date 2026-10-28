from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import NotificationType
from app.common.ids import new_id
from app.common.timeutil import now_kst
from app.core.database import Base, enum_col


class Notification(Base):
    __tablename__ = "Notifications"
    __table_args__ = (Index("IDX_NOTIFICATIONS_USER", "user_id", "is_read", "created_at"),)

    notification_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("Users.user_id"))
    type: Mapped[NotificationType] = mapped_column(enum_col(NotificationType, 40))
    title: Mapped[str] = mapped_column(String(50))
    body: Mapped[str] = mapped_column(String(255))
    target_url: Mapped[str | None] = mapped_column(String(255))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=now_kst)
