import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.domains.merit.models import MeisterGradeCriteria, MeisterScoreItem
from app.domains.mileage.models import PointRule
from scripts.import_reference import ReferenceError, import_reference, parse
from tests.factories import make_student

EXAMPLE = Path(__file__).resolve().parent.parent / "scripts" / "reference.example.json"


async def count(db, model):
    return await db.scalar(select(func.count()).select_from(model))


async def test_example_file_imports_and_is_served_by_the_api(db, make_client, tmp_path):
    report = await import_reference(str(EXAMPLE))
    # 테스트 DB에는 예시 시드가 들어 있어 같은 항목은 건너뛰고, 새 항목만 추가한다
    assert report == {
        "scoreItems": (0, 2), "gradeCriteria": (1, 0), "pointRules": (0, 2),
        "academicSchedules": (1, 0), "themePresets": (1, 0), "contestTags": (0, 3),
    }

    c = await make_client(await make_student(db))
    assert (await c.get("/api/meister/grade-criteria")).json()["registered"] is True
    assert [p["name"] for p in (await c.get("/api/theme/presets")).json()["items"]] == ["밤하늘 별"]
    sched = (await c.get("/api/academic-schedules", params={"from": "2026-12-01"})).json()["items"]
    assert sched[0]["title"] == "2학기 기말고사"
    assert any(i["name"] == "어학 시험" for i in (await c.get("/api/meister/score-items")).json()["items"])


async def test_import_is_idempotent(db):
    first = await import_reference(str(EXAMPLE))
    before = (await count(db, MeisterScoreItem), await count(db, PointRule), await count(db, MeisterGradeCriteria))
    second = await import_reference(str(EXAMPLE))
    assert all(created == 0 for created, _ in second.values())
    assert (await count(db, MeisterScoreItem), await count(db, PointRule), await count(db, MeisterGradeCriteria)) == before
    assert first


def write(tmp_path, data) -> str:
    p = tmp_path / "ref.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


@pytest.mark.parametrize(
    "data,needle",
    [
        ({"scoreItems": [{"scoreType": "NOPE", "name": "x", "maxPoints": 1}]}, "scoreItems.0.scoreType"),
        ({"scoreItems": [{"scoreType": "JOB_BASIC", "name": "x", "maxPoints": 0}]}, "scoreItems.0.maxPoints"),
        ({"pointRules": [{"type": "MERIT", "category": "봉사", "title": "x", "points": 1}, {"type": "MERIT"}]}, "pointRules.1"),
        ({"academicSchedules": [{"type": "EXAM", "title": "x", "startDate": "2026-12-11", "endDate": "2026-12-08"}]}, "endDate"),
        ({"gradeCriteria": [{"scoreType": "JOB_BASIC", "maxRawScore": 10, "conversionRate": 1,
                             "grades": [{"grade": "A", "minRawScore": 1}, {"grade": "A", "minRawScore": 2}]}]}, "중복"),
        ({"contestTags": ["열한글자이름입니다아아"]}, "contestTags.0"),
        ({"unknownSection": []}, "unknownSection"),
    ],
)
def test_invalid_files_are_rejected_with_location(tmp_path, data, needle):
    with pytest.raises(ReferenceError) as e:
        parse(write(tmp_path, data))
    assert needle in str(e.value)


async def test_nothing_is_saved_when_any_row_is_invalid(db, tmp_path):
    before = await count(db, MeisterScoreItem)
    bad = {"scoreItems": [{"scoreType": "JOB_BASIC", "name": "새 항목", "maxPoints": 5}],
           "pointRules": [{"type": "MERIT", "category": "봉사", "title": "x", "points": -1}]}
    with pytest.raises(ReferenceError):
        await import_reference(write(tmp_path, bad))
    assert await count(db, MeisterScoreItem) == before


async def test_duplicate_rows_inside_one_file_are_collapsed(db, tmp_path):
    row = {"scoreType": "JOB_BASIC", "name": "중복 항목", "maxPoints": 5}
    report = await import_reference(write(tmp_path, {"scoreItems": [row, row]}))
    assert report["scoreItems"] == (1, 1)
