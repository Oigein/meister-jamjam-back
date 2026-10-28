from app.common.schemas import CamelModel


class ProfileUpdate(CamelModel):
    """키를 보내지 않으면 변경 없음, null·빈 문자열이면 삭제 (model_fields_set으로 구분)."""

    github_url: str | None = None
    linkedin_url: str | None = None
