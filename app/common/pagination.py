import math
from typing import Generic, TypeVar

from app.common.schemas import CamelModel

T = TypeVar("T")


class Page(CamelModel, Generic[T]):
    items: list[T]
    page: int
    size: int
    total_elements: int
    total_pages: int


def make_page(items: list, page: int, size: int, total: int) -> dict:
    """Pydantic 모델을 만들지 않고 camelCase dict로 돌려준다 (라우터에서 response_model 없이 사용)."""
    return {
        "items": items,
        "page": page,
        "size": size,
        "totalElements": total,
        "totalPages": math.ceil(total / size) if size else 0,
    }


def offset(page: int, size: int) -> int:
    return (page - 1) * size
