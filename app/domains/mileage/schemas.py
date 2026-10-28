from pydantic import Field

from app.common.enums import PointType
from app.common.schemas import CamelModel


class MeritPointCreate(CamelModel):
    student_id: str
    type: PointType
    rule_id: int | None = None
    title: str = Field(min_length=1, max_length=20)
    content: str | None = Field(None, max_length=50)
    points: int = Field(ge=1)
