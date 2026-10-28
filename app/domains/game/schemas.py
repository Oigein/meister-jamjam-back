from pydantic import Field

from app.common.enums import PinballMode
from app.common.schemas import CamelModel


class SeatPos(CamelModel):
    row: int = Field(ge=1)
    col: int = Field(ge=1)


class Layout(CamelModel):
    rows: int = Field(ge=1, le=10)
    cols: int = Field(ge=1, le=10)
    group_shape: str | None = Field(None, pattern=r"^\d+x\d+$")  # 모둠형 "2x2" 등. 없으면 일반 배치
    disabled_seats: list[SeatPos] = []


class FixedSeat(CamelModel):
    student_id: str
    row: int
    col: int


class SeatDrawBody(CamelModel):
    grade: int
    class_no: int
    layout: Layout
    excluded_student_ids: list[str] = []
    fixed_seats: list[FixedSeat] = []
    avoid_previous_seat: bool = False


class PinballBody(CamelModel):
    grade: int
    class_no: int
    mode: PinballMode
    winner_count: int = Field(ge=1)
    excluded_student_ids: list[str] = []
    allow_duplicate: bool = False
    previous_draw_id: str | None = None
