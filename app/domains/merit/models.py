from datetime import datetime

from sqlalchemy import JSON, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import AnalysisStatus, EvidenceStatus, ScoreType
from app.common.ids import new_id
from app.common.timeutil import now_kst
from app.core.database import Base, enum_col


class MeisterScoreItem(Base):
    __tablename__ = "MeisterScoreItems"

    item_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    score_type: Mapped[ScoreType] = mapped_column(enum_col(ScoreType))
    name: Mapped[str] = mapped_column(String(50))
    max_points: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(String(255))


class MeisterGradeCriteria(Base):
    __tablename__ = "MeisterGradeCriteria"

    criteria_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    score_type: Mapped[ScoreType] = mapped_column(enum_col(ScoreType), unique=True)
    max_raw_score: Mapped[int] = mapped_column(Integer)
    conversion_rate: Mapped[float] = mapped_column(Float)
    grades: Mapped[list] = mapped_column(JSON)  # [{"grade": "A", "minRawScore": 100}, ...]


class Evidence(Base):
    __tablename__ = "Evidences"

    evidence_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    student_id: Mapped[str] = mapped_column(String(36), ForeignKey("Students.student_id"), index=True)
    title: Mapped[str] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(String(200))
    score_type_hint: Mapped[ScoreType | None] = mapped_column(enum_col(ScoreType))
    file_key: Mapped[str] = mapped_column(String(255))
    file_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[EvidenceStatus] = mapped_column(enum_col(EvidenceStatus), default=EvidenceStatus.PENDING)
    analysis_status: Mapped[AnalysisStatus] = mapped_column(
        enum_col(AnalysisStatus), default=AnalysisStatus.PROCESSING
    )
    ai_result: Mapped[dict | None] = mapped_column(JSON)
    analyzed_at: Mapped[datetime | None]
    reject_reason: Mapped[str | None] = mapped_column(String(200))
    approved_points: Mapped[int | None] = mapped_column(Integer)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("Users.user_id"))
    reviewed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=now_kst)


class MeisterScoreDetail(Base):
    __tablename__ = "MeisterScoreDetails"

    meister_point_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    teacher_id: Mapped[str] = mapped_column(String(36), ForeignKey("Users.user_id"))
    student_id: Mapped[str] = mapped_column(String(36), ForeignKey("Students.student_id"), index=True)
    score_type: Mapped[ScoreType] = mapped_column(enum_col(ScoreType))
    item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("MeisterScoreItems.item_id"))
    evidence_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("Evidences.evidence_id"))
    content: Mapped[str] = mapped_column(String(50))
    points: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=now_kst)
