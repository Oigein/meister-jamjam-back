from enum import StrEnum


class Role(StrEnum):
    STUDENT = "STUDENT"
    TEACHER = "TEACHER"
    ADMIN = "ADMIN"


class ScoreType(StrEnum):
    JOB_BASIC = "JOB_BASIC"
    MAJOR_SKILL = "MAJOR_SKILL"
    CHARACTER_JOB_ETHIC = "CHARACTER_JOB_ETHIC"
    HUMANITIES_LITERACY = "HUMANITIES_LITERACY"
    FOREIGN_LANGUAGE = "FOREIGN_LANGUAGE"


SCORE_LABELS = {
    ScoreType.JOB_BASIC: "직업기초능력",
    ScoreType.MAJOR_SKILL: "전공직무능력",
    ScoreType.CHARACTER_JOB_ETHIC: "인성·직업윤리",
    ScoreType.HUMANITIES_LITERACY: "인문학적 소양",
    ScoreType.FOREIGN_LANGUAGE: "외국어능력",
}

# ScoreType -> Students 컬럼 이름
SCORE_COLUMNS = {
    ScoreType.JOB_BASIC: "job_basic_point",
    ScoreType.MAJOR_SKILL: "major_skill_point",
    ScoreType.CHARACTER_JOB_ETHIC: "character_job_ethic_point",
    ScoreType.HUMANITIES_LITERACY: "humanities_literacy_point",
    ScoreType.FOREIGN_LANGUAGE: "foreign_language_point",
}


class PointType(StrEnum):
    MERIT = "MERIT"
    DEMERIT = "DEMERIT"


class ContestScope(StrEnum):
    IN_SCHOOL = "IN_SCHOOL"
    OUT_SCHOOL = "OUT_SCHOOL"


class EvidenceStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AnalysisStatus(StrEnum):
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"


class SelfReportStatus(StrEnum):
    UNREAD = "UNREAD"
    READ = "READ"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"


class SelfReportType(StrEnum):
    LOST_FOUND = "LOST_FOUND"
    SCHOOL_RULE = "SCHOOL_RULE"
    PEER_RELATION = "PEER_RELATION"
    COUNSELING = "COUNSELING"
    ETC = "ETC"


class PreferredHandling(StrEnum):
    MEETING = "MEETING"
    WRITTEN_REPLY = "WRITTEN_REPLY"
    NOTICE_ONLY = "NOTICE_ONLY"


class ChangeReason(StrEnum):
    SUBJECT = "SUBJECT"
    COUNSELING = "COUNSELING"
    ETC = "ETC"


class FontScale(StrEnum):
    XS = "XS"
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"


class BackgroundType(StrEnum):
    NONE = "NONE"
    GIF = "GIF"
    MP4 = "MP4"


class BackgroundSource(StrEnum):
    PRESET = "PRESET"
    UPLOAD = "UPLOAD"


class BackgroundFit(StrEnum):
    COVER = "COVER"
    TILE = "TILE"
    CONTAIN = "CONTAIN"


class DrawType(StrEnum):
    SEAT = "SEAT"
    PINBALL = "PINBALL"


class PinballMode(StrEnum):
    DROP = "DROP"
    BUMPER = "BUMPER"


class ScheduleType(StrEnum):
    EXAM = "EXAM"
    PROJECT = "PROJECT"
    EVENT = "EVENT"


class NotificationType(StrEnum):
    EVIDENCE_APPROVED = "EVIDENCE_APPROVED"
    EVIDENCE_REJECTED = "EVIDENCE_REJECTED"
    MEISTER_SCORE_CHANGED = "MEISTER_SCORE_CHANGED"
    SELF_REPORT_RECEIVED = "SELF_REPORT_RECEIVED"
    SELF_REPORT_STATUS_CHANGED = "SELF_REPORT_STATUS_CHANGED"
    SELF_REPORT_REPLIED = "SELF_REPORT_REPLIED"
