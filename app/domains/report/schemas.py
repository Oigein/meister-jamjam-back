from pydantic import Field

from app.common.enums import ChangeReason, PreferredHandling, SelfReportStatus, SelfReportType
from app.common.schemas import CamelModel


class SelfReportCreate(CamelModel):
    type: SelfReportType
    title: str = Field(min_length=1, max_length=50)
    content: str = Field(min_length=1, max_length=2000)
    recipient_ids: list[str] = Field(min_length=1)
    change_reason: ChangeReason | None = None
    preferred_handling: PreferredHandling
    attachment_ids: list[str] = Field(default=[], max_length=3)


class SelfReportUpdate(CamelModel):
    """바꿀 필드만 보낸다 (model_fields_set으로 구분)."""

    type: SelfReportType | None = None
    title: str | None = Field(None, min_length=1, max_length=50)
    content: str | None = Field(None, min_length=1, max_length=2000)
    recipient_ids: list[str] | None = Field(None, min_length=1)
    change_reason: ChangeReason | None = None
    preferred_handling: PreferredHandling | None = None
    attachment_ids: list[str] | None = Field(None, max_length=3)


class StatusBody(CamelModel):
    status: SelfReportStatus


class ReplyBody(CamelModel):
    content: str = Field(min_length=1, max_length=1000)
