from pydantic import Field

from app.common.enums import ContestScope
from app.common.schemas import CamelModel, KstDateTime


class CategoryCreate(CamelModel):
    name: str


class ContestWrite(CamelModel):
    contest_name: str = Field(min_length=1, max_length=30)
    content: str = Field(min_length=1)
    scope: ContestScope  # 기본값 없음
    category_id: int
    tag_ids: list[int] = []
    start_at: KstDateTime
    finish_at: KstDateTime
    # 대회 추천용 정보 (대회 수정 API로 관리)
    expected_score: int | None = Field(None, ge=0)
    difficulty: int | None = Field(None, ge=1, le=5)
    prep_hours: int | None = Field(None, ge=1)
    is_verified: bool | None = None
