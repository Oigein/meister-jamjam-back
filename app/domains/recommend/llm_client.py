"""LLM 클라이언트 인터페이스. 대회 추천·챗 API는 Phase 7에서 이 인터페이스 위에 구현한다."""
from typing import Protocol


class LLMClient(Protocol):
    async def complete(self, system: str, user: str, *, timeout: float = 30.0) -> str: ...
