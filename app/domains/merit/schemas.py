from pydantic import Field

from app.common.enums import ScoreType
from app.common.schemas import CamelModel


class ApproveBody(CamelModel):
    score_type: ScoreType
    item_id: int
    points: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=50)


class RejectBody(CamelModel):
    reason: str = Field(min_length=1, max_length=200)


class DirectGrantBody(CamelModel):
    student_id: str
    score_type: ScoreType
    item_id: int
    points: int  # 오류 정정을 위한 음수(감점)도 허용, 0은 불가
    content: str = Field(min_length=1, max_length=50)
