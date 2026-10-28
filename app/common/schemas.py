from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, PlainSerializer
from pydantic.alias_generators import to_camel

from app.common.timeutil import to_iso, to_naive_kst


class CamelModel(BaseModel):
    """요청·응답 JSON은 camelCase, 코드는 snake_case."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


# 입력은 KST naive로 맞추고, 출력은 항상 +09:00 ISO 8601
KstDateTime = Annotated[datetime, AfterValidator(to_naive_kst), PlainSerializer(to_iso, return_type=str)]
