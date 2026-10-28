"""증빙자료 AI 분석(OCR + LLM) 인터페이스. 실제 연동은 Phase 7에서 구현한다.

기본값은 '설정되지 않음'이라 분석이 FAILED로 끝나고, 교사가 증빙을 직접 보고 승인·반려한다.
`set_analyzer()`로 구현체를 바꾼다. 구현체는 아래 모양의 dict를 돌려준다.

    {
      "extracted": {"kind": "CERTIFICATE", "name": "...", "issuer": "...", "award": None, "achievedAt": "2026-09-10"},
      "recommendation": {"scoreType": "MAJOR_SKILL", "itemId": 12, "itemName": "...", "expectedPoints": 10, "reason": "..."},
    }
"""
from typing import Protocol


class AnalysisUnavailable(Exception):
    pass


class EvidenceAnalyzer(Protocol):
    async def analyze(
        self, *, file_bytes: bytes, content_type: str, title: str, hint: str | None, items: list[dict]
    ) -> dict: ...


class DisabledAnalyzer:
    async def analyze(self, **_: object) -> dict:
        raise AnalysisUnavailable("AI 분석기가 설정되지 않았습니다.")


_analyzer: EvidenceAnalyzer = DisabledAnalyzer()


def get_analyzer() -> EvidenceAnalyzer:
    return _analyzer


def set_analyzer(analyzer: EvidenceAnalyzer) -> None:
    global _analyzer
    _analyzer = analyzer
