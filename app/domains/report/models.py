from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import ChangeReason, PreferredHandling, SelfReportStatus, SelfReportType
from app.common.ids import new_id
from app.common.timeutil import now_kst
from app.core.database import Base, enum_col


class SelfReport(Base):
    __tablename__ = "SelfReport"

    report_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    student_id: Mapped[str] = mapped_column(String(36), ForeignKey("Students.student_id"), index=True)
    type: Mapped[SelfReportType] = mapped_column(enum_col(SelfReportType))
    title: Mapped[str] = mapped_column(Text)  # AES-256-GCM 암호문
    content: Mapped[str] = mapped_column(Text)  # AES-256-GCM 암호문
    preferred_handling: Mapped[PreferredHandling] = mapped_column(enum_col(PreferredHandling))
    status: Mapped[SelfReportStatus] = mapped_column(
        enum_col(SelfReportStatus), default=SelfReportStatus.UNREAD
    )
    change_reason: Mapped[ChangeReason | None] = mapped_column(enum_col(ChangeReason))
    created_at: Mapped[datetime] = mapped_column(default=now_kst)
    updated_at: Mapped[datetime] = mapped_column(default=now_kst)


class SelfReportRecipient(Base):
    __tablename__ = "SelfReportRecipients"

    report_id: Mapped[str] = mapped_column(String(36), ForeignKey("SelfReport.report_id"), primary_key=True)
    teacher_id: Mapped[str] = mapped_column(String(36), ForeignKey("Teachers.teacher_id"), primary_key=True)
    read_at: Mapped[datetime | None]


class SelfReportAttachment(Base):
    __tablename__ = "SelfReportAttachments"

    attachment_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    report_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("SelfReport.report_id"))
    uploader_id: Mapped[str] = mapped_column(String(36), ForeignKey("Users.user_id"))
    file_name: Mapped[str] = mapped_column(Text)  # 암호문
    content_type: Mapped[str] = mapped_column(String(100))
    file_key: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(default=now_kst)


class SelfReportReply(Base):
    __tablename__ = "SelfReportReplies"

    reply_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(String(36), ForeignKey("SelfReport.report_id"), index=True)
    author_id: Mapped[str] = mapped_column(String(36), ForeignKey("Users.user_id"))
    content: Mapped[str] = mapped_column(Text)  # 암호문
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)  # 상대방이 읽었는지
    created_at: Mapped[datetime] = mapped_column(default=now_kst)
