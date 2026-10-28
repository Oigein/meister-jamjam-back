"""기준 데이터(평가항목·환산 등급·상벌점 기준·학사 일정·테마 배경 갤러리·대회 태그)를 JSON으로 가져온다.

    python -m scripts.import_reference reference.json

형식은 `scripts/reference.example.json`을 본다. 섹션은 모두 선택이다.
- 이미 있는 항목은 건너뛴다 (평가항목: 영역+이름 / 환산 기준: 영역 / 상벌점 기준: 구분+분류+항목명 /
  학사 일정: 종류+제목+시작일 / 배경: 종류+이름 / 태그: 이름)
- 잘못된 값이 하나라도 있으면 어디가 문제인지 알려 주고 아무것도 저장하지 않는다.
- 서버를 처음 켜기 전에 SEED_ON_STARTUP=false로 두지 않으면 예시 시드 데이터가 먼저 들어간다.
"""
import asyncio
import json
import sys
from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401
from app.common.enums import BackgroundType, PointType, ScheduleType, ScoreType
from app.core.database import get_sessionmaker
from app.domains.contest.models import AcademicSchedule, ContestTag
from app.domains.merit.models import MeisterGradeCriteria, MeisterScoreItem
from app.domains.mileage.models import PointRule
from app.domains.theme.models import ThemePreset

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Row(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class ScoreItemRow(Row):
    score_type: ScoreType
    name: Annotated[Text, Field(max_length=50)]
    max_points: int = Field(ge=1)
    description: Annotated[str, Field(max_length=255)] | None = None


class GradeRow(Row):
    grade: Annotated[Text, Field(max_length=10)]
    min_raw_score: int = Field(ge=0)


class GradeCriteriaRow(Row):
    score_type: ScoreType
    max_raw_score: int = Field(ge=1)
    conversion_rate: float = Field(gt=0)
    grades: list[GradeRow] = Field(min_length=1)


class PointRuleRow(Row):
    type: PointType
    category: Annotated[Text, Field(max_length=20)]
    title: Annotated[Text, Field(max_length=50)]
    points: int = Field(ge=1)
    description: Annotated[str, Field(max_length=255)] | None = None
    note: Annotated[str, Field(max_length=255)] | None = None


class ScheduleRow(Row):
    type: ScheduleType
    title: Annotated[Text, Field(max_length=100)]
    start_date: date
    end_date: date


class PresetRow(Row):
    type: BackgroundType
    name: Annotated[Text, Field(max_length=50)]
    file_url: Annotated[Text, Field(max_length=500)]
    thumbnail_url: Annotated[str, Field(max_length=500)] | None = None
    sort_order: int = 0


class ReferenceFile(Row):
    score_items: list[ScoreItemRow] = []
    grade_criteria: list[GradeCriteriaRow] = []
    point_rules: list[PointRuleRow] = []
    academic_schedules: list[ScheduleRow] = []
    theme_presets: list[PresetRow] = []
    contest_tags: list[Annotated[Text, Field(max_length=10)]] = []


class ReferenceError(Exception):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def parse(path: str) -> ReferenceFile:
    with open(path, encoding="utf-8-sig") as f:
        raw = json.load(f)
    try:
        data = ReferenceFile.model_validate(raw)
    except ValidationError as exc:
        problems = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        raise ReferenceError(problems) from exc
    problems = []
    for i, s in enumerate(data.academic_schedules):
        if s.end_date < s.start_date:
            problems.append(f"academicSchedules.{i}: endDate가 startDate보다 빠릅니다")
    for i, c in enumerate(data.grade_criteria):
        if len({g.grade for g in c.grades}) != len(c.grades):
            problems.append(f"gradeCriteria.{i}: 등급 이름이 중복됩니다")
    if problems:
        raise ReferenceError(problems)
    return data


async def _exists(db: AsyncSession, model, *conds) -> bool:
    return await db.scalar(select(model).where(*conds).limit(1)) is not None


async def apply(db: AsyncSession, data: ReferenceFile) -> dict[str, tuple[int, int]]:
    result: dict[str, list[int]] = {}

    async def put(section: str, exists: bool, make) -> None:
        counts = result.setdefault(section, [0, 0])
        if exists:
            counts[1] += 1
        else:
            db.add(make())
            counts[0] += 1
            await db.flush()  # 같은 파일 안의 중복도 건너뛰게 한다

    for r in data.score_items:
        await put("scoreItems", await _exists(db, MeisterScoreItem, MeisterScoreItem.score_type == r.score_type, MeisterScoreItem.name == r.name),
                  lambda r=r: MeisterScoreItem(score_type=r.score_type, name=r.name, max_points=r.max_points, description=r.description))
    for r in data.grade_criteria:
        await put("gradeCriteria", await _exists(db, MeisterGradeCriteria, MeisterGradeCriteria.score_type == r.score_type),
                  lambda r=r: MeisterGradeCriteria(score_type=r.score_type, max_raw_score=r.max_raw_score, conversion_rate=r.conversion_rate,
                                                   grades=[{"grade": g.grade, "minRawScore": g.min_raw_score} for g in r.grades]))
    for r in data.point_rules:
        await put("pointRules", await _exists(db, PointRule, PointRule.type == r.type, PointRule.category == r.category, PointRule.title == r.title, PointRule.is_active.is_(True)),
                  lambda r=r: PointRule(type=r.type, category=r.category, title=r.title, points=r.points, description=r.description, note=r.note, is_active=True))
    for r in data.academic_schedules:
        await put("academicSchedules", await _exists(db, AcademicSchedule, AcademicSchedule.type == r.type, AcademicSchedule.title == r.title, AcademicSchedule.start_date == r.start_date),
                  lambda r=r: AcademicSchedule(type=r.type, title=r.title, start_date=r.start_date, end_date=r.end_date))
    for r in data.theme_presets:
        await put("themePresets", await _exists(db, ThemePreset, ThemePreset.type == r.type, ThemePreset.name == r.name),
                  lambda r=r: ThemePreset(type=r.type, name=r.name, file_url=r.file_url, thumbnail_url=r.thumbnail_url, sort_order=r.sort_order))
    for name in data.contest_tags:
        await put("contestTags", await _exists(db, ContestTag, ContestTag.tag_name == name), lambda name=name: ContestTag(tag_name=name))
    return {k: (v[0], v[1]) for k, v in result.items()}


async def import_reference(path: str) -> dict[str, tuple[int, int]]:
    data = parse(path)
    async with get_sessionmaker()() as db:
        try:
            counts = await apply(db, data)
            await db.commit()  # 전체를 한 트랜잭션으로
        except Exception:
            await db.rollback()
            raise
    return counts


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    try:
        report = asyncio.run(import_reference(sys.argv[1]))
    except ReferenceError as exc:
        sys.exit("가져오지 못했습니다. 아무것도 저장하지 않았습니다.\n" + "\n".join(f" - {p}" for p in exc.problems))
    for section, (created, skipped) in report.items():
        print(f"{section}: 추가 {created}, 이미 있어 건너뜀 {skipped}")
