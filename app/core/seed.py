"""기본 데이터 시드. 비어 있는 테이블에만 넣는다.

평가항목·상벌점 기준은 형식을 보여 주는 예시 값이다. 운영에서는 학교 기준표로 교체해야 한다.
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import PointType, ScoreType
from app.domains.contest.models import ContestCategory, ContestTag
from app.domains.merit.models import MeisterScoreItem
from app.domains.mileage.models import PointRule

DEFAULT_CATEGORIES = ["공모전", "경진대회", "해커톤"]
DEFAULT_TAGS = ["백엔드", "프론트엔드", "AI", "앱", "임베디드", "보안", "게임", "기타"]

SCORE_ITEMS = [
    (ScoreType.JOB_BASIC, "직업기초 교육 이수", 20, None),
    (ScoreType.JOB_BASIC, "성실성 평가", 20, None),
    (ScoreType.MAJOR_SKILL, "국가기술자격증", 30, "기능사 10점, 산업기사 20점"),
    (ScoreType.MAJOR_SKILL, "대회 입상", 40, None),
    (ScoreType.CHARACTER_JOB_ETHIC, "봉사활동", 20, None),
    (ScoreType.CHARACTER_JOB_ETHIC, "리더십 활동", 20, None),
    (ScoreType.HUMANITIES_LITERACY, "독서 활동", 20, None),
    (ScoreType.HUMANITIES_LITERACY, "문화 체험", 10, None),
    (ScoreType.FOREIGN_LANGUAGE, "어학 시험", 30, None),
    (ScoreType.FOREIGN_LANGUAGE, "외국어 활동", 20, None),
]

POINT_RULES = [
    (PointType.MERIT, "봉사", "교내 봉사활동", 3, "담당 교사가 확인한 교내 봉사활동 1회", "하루 1회만 인정"),
    (PointType.MERIT, "학습", "학업 우수", 2, None, None),
    (PointType.DEMERIT, "생활", "지각", 1, "조회 시작 이후 등교", None),
    (PointType.DEMERIT, "기숙사", "점호 불참", 2, None, None),
]


async def _empty(db: AsyncSession, model) -> bool:
    return (await db.scalar(select(func.count()).select_from(model))) == 0


async def seed_defaults(db: AsyncSession) -> None:
    if await _empty(db, ContestCategory):
        for name in DEFAULT_CATEGORIES:
            db.add(ContestCategory(name=name, normalized_name=name.replace(" ", "").lower(), is_default=True))
    if await _empty(db, ContestTag):
        for name in DEFAULT_TAGS:
            db.add(ContestTag(tag_name=name))
    if await _empty(db, MeisterScoreItem):
        for score_type, name, max_points, desc in SCORE_ITEMS:
            db.add(MeisterScoreItem(score_type=score_type, name=name, max_points=max_points, description=desc))
    if await _empty(db, PointRule):
        for type_, category, title, points, desc, note in POINT_RULES:
            db.add(PointRule(type=type_, category=category, title=title, points=points, description=desc, note=note))
    await db.commit()
