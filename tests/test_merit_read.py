from datetime import datetime

from app.common.enums import ScoreType
from app.domains.merit.models import Evidence, MeisterGradeCriteria, MeisterScoreDetail, MeisterScoreItem
from tests.factories import make_student, make_teacher


async def test_ranking_ties_order_and_is_me(make_client, db):
    a = await make_student(db, "가", 2, 1, 1, major_skill_point=100)
    b = await make_student(db, "나", 1, 2, 3, major_skill_point=100, job_basic_point=0)
    c = await make_student(db, "다", 3, 1, 1, major_skill_point=50)
    d = await make_student(db, "라", 2, 1, 2)  # 0점
    cl = await make_client(c)
    r = (await cl.get("/api/meister/rankings")).json()
    assert [(i["name"], i["rank"]) for i in r["items"]] == [("나", 1), ("가", 1), ("다", 3), ("라", 4)]
    # 동점은 학년 → 반 → 번호 순, 다음 순위는 동점자 수만큼 건너뜀 (1, 1, 3, 4)
    assert [i["isMe"] for i in r["items"]] == [False, False, True, False]
    assert r["myRank"] == {"studentId": c.user_id, "rank": 3, "totalScore": 50, "page": 1}
    assert r["grade"] is None and r["size"] == 20 and r["totalElements"] == 4 and r["totalPages"] == 1


async def test_ranking_grade_scope_is_computed_separately(make_client, db):
    await make_student(db, "1학년", 1, 1, 1, major_skill_point=10)
    me = await make_student(db, "2학년A", 2, 1, 1, major_skill_point=5)
    await make_student(db, "2학년B", 2, 1, 2, major_skill_point=50)
    cl = await make_client(me)
    r = (await cl.get("/api/meister/rankings", params={"grade": 2})).json()
    assert r["grade"] == 2 and [(i["name"], i["rank"]) for i in r["items"]] == [("2학년B", 1), ("2학년A", 2)]
    assert r["myRank"]["rank"] == 2
    # 선택한 학년에 내가 없으면 myRank는 null
    r = (await cl.get("/api/meister/rankings", params={"grade": 1})).json()
    assert r["myRank"] is None and len(r["items"]) == 1 and r["items"][0]["rank"] == 1


async def test_ranking_pagination_and_my_page(make_client, db):
    users = [await make_student(db, f"학생{n:02d}", 1, 1, n, major_skill_point=100 - n) for n in range(1, 26)]
    me = users[22]  # 23위
    cl = await make_client(me)
    p1 = (await cl.get("/api/meister/rankings")).json()
    assert len(p1["items"]) == 20 and p1["totalElements"] == 25 and p1["totalPages"] == 2
    assert p1["myRank"]["rank"] == 23 and p1["myRank"]["page"] == 2
    p2 = (await cl.get("/api/meister/rankings", params={"page": 2})).json()
    assert [i["rank"] for i in p2["items"]] == [21, 22, 23, 24, 25] and p2["page"] == 2  # 순위는 페이지가 바뀌어도 이어짐
    for bad in ("0", "-3", "abc", "99", ""):
        r = (await cl.get("/api/meister/rankings", params={"page": bad})).json()
        assert r["page"] == 1 and r["items"][0]["rank"] == 1


async def test_ranking_errors_and_empty(make_client, db):
    t = await make_teacher(db)
    cl = await make_client(t)
    r = await cl.get("/api/meister/rankings")
    assert r.status_code == 200
    assert r.json()["items"] == [] and r.json()["totalElements"] == 0 and r.json()["myRank"] is None
    for bad in ("0", "4", "x"):
        resp = await cl.get("/api/meister/rankings", params={"grade": bad})
        assert resp.status_code == 400 and resp.json()["code"] == "VALIDATION_FAILED"
    assert (await (await make_client()).get("/api/meister/rankings")).status_code == 401


async def test_student_detail_and_404(make_client, db):
    await make_student(db, "일등", 1, 1, 1, major_skill_point=90)
    me = await make_student(db, "나", 2, 1, 5, major_skill_point=10, job_basic_point=5)
    me_row_url = "https://github.com/octocat"
    from app.domains.user.models import Student

    (await db.get(Student, me.user_id)).github_url = me_row_url
    await db.commit()
    cl = await make_client(me)
    r = (await cl.get(f"/api/students/{me.user_id}")).json()
    assert r == {"studentId": me.user_id, "name": "나", "grade": 2, "classNo": 1, "number": 5, "totalScore": 15,
                 "rank": 2, "githubUrl": me_row_url, "linkedinUrl": None, "isMe": True}
    for bad in ("00000000-0000-4000-8000-000000000000", "not-a-uuid"):
        r = await cl.get(f"/api/students/{bad}")
        assert r.status_code == 404 and r.json()["code"] == "STUDENT_NOT_FOUND"


async def test_meister_scores_always_five_areas_and_conversion(make_client, db):
    me = await make_student(db, "나", major_skill_point=120)
    cl = await make_client(me)
    r = (await cl.get(f"/api/students/{me.user_id}/meister-scores")).json()
    assert r["criteriaRegistered"] is False and len(r["areas"]) == 5
    assert all(a["convertedScore"] is None and a["grade"] is None for a in r["areas"])
    assert [a["rawScore"] for a in r["areas"]] == [0, 120, 0, 0, 0] and r["totalScore"] == 120

    db.add(MeisterGradeCriteria(score_type=ScoreType.MAJOR_SKILL, max_raw_score=150, conversion_rate=0.2,
                                grades=[{"grade": "C", "minRawScore": 30}, {"grade": "A", "minRawScore": 100},
                                        {"grade": "B", "minRawScore": 60}]))
    await db.commit()
    major = next(a for a in (await cl.get(f"/api/students/{me.user_id}/meister-scores")).json()["areas"]
                 if a["scoreType"] == "MAJOR_SKILL")
    assert major["convertedScore"] == 24.0 and major["grade"] == "A" and major["label"] == "전공직무능력"

    crit = (await cl.get("/api/meister/grade-criteria")).json()
    assert crit["registered"] is True and crit["areas"][0]["grades"][0] == {"grade": "A", "minRawScore": 100}


async def test_grade_criteria_unregistered(make_client, db):
    cl = await make_client(await make_student(db))
    assert (await cl.get("/api/meister/grade-criteria")).json() == {"registered": False, "areas": []}


async def test_history_filters_order_and_evidence_visibility(make_client, db):
    owner = await make_student(db, "주인")
    other = await make_student(db, "다른학생")
    teacher = await make_teacher(db, "박선생")
    from sqlalchemy import select

    item = await db.scalar(select(MeisterScoreItem).where(MeisterScoreItem.score_type == ScoreType.MAJOR_SKILL))
    ev = Evidence(student_id=owner.user_id, title="자격증", file_key="k", file_name="자격증.pdf",
                  content_type="application/pdf")
    db.add(ev)
    await db.flush()
    db.add_all([
        MeisterScoreDetail(teacher_id=teacher.user_id, student_id=owner.user_id, score_type=ScoreType.MAJOR_SKILL,
                           item_id=item.item_id, evidence_id=ev.evidence_id, content="정보처리기능사 취득", points=10,
                           created_at=datetime(2026, 10, 2, 10, 15)),
        MeisterScoreDetail(teacher_id=teacher.user_id, student_id=owner.user_id, score_type=ScoreType.JOB_BASIC,
                           content="감점 정정", points=-3, created_at=datetime(2026, 10, 5, 9, 0)),
    ])
    await db.commit()

    url = f"/api/students/{owner.user_id}/meister-scores/history"
    as_owner = await make_client(owner)
    r = (await as_owner.get(url)).json()
    assert [i["points"] for i in r["items"]] == [-3, 10]  # 최신순, 감소(음수)도 같은 목록
    major = r["items"][1]
    assert major["itemName"] == "국가기술자격증" and major["teacher"]["name"] == "박선생"
    assert major["evidence"] == {"evidenceId": ev.evidence_id, "fileName": "자격증.pdf"}
    assert major["createdAt"] == "2026-10-02T10:15:00+09:00"
    assert [i["points"] for i in (await as_owner.get(url, params={"order": "asc"})).json()["items"]] == [10, -3]
    assert (await as_owner.get(url, params={"scoreType": "JOB_BASIC"})).json()["totalElements"] == 1
    assert (await as_owner.get(url, params={"order": "up"})).status_code == 400

    # 다른 학생에게는 증빙이 보이지 않고, 교사에게는 보인다
    other_items = (await (await make_client(other)).get(url)).json()["items"]
    assert all(i["evidence"] is None for i in other_items)
    teacher_items = (await (await make_client(teacher)).get(url)).json()["items"]
    assert teacher_items[1]["evidence"]["fileName"] == "자격증.pdf"


async def test_score_items_endpoint(make_client, db):
    cl = await make_client(await make_student(db))
    all_items = (await cl.get("/api/meister/score-items")).json()["items"]
    assert len(all_items) == 10
    major = (await cl.get("/api/meister/score-items", params={"scoreType": "MAJOR_SKILL"})).json()["items"]
    assert {i["scoreType"] for i in major} == {"MAJOR_SKILL"} and major[0]["maxPoints"] == 30


async def test_meister_scores_include_per_item_points(make_client, db):
    from sqlalchemy import select

    me = await make_student(db, "나", major_skill_point=12)
    teacher = await make_teacher(db)
    major = (await db.scalars(select(MeisterScoreItem).where(MeisterScoreItem.score_type == ScoreType.MAJOR_SKILL)
                              .order_by(MeisterScoreItem.item_id))).all()
    db.add_all([
        MeisterScoreDetail(teacher_id=teacher.user_id, student_id=me.user_id, score_type=ScoreType.MAJOR_SKILL,
                           item_id=major[0].item_id, content="a", points=10),
        MeisterScoreDetail(teacher_id=teacher.user_id, student_id=me.user_id, score_type=ScoreType.MAJOR_SKILL,
                           item_id=major[0].item_id, content="b", points=5),
        MeisterScoreDetail(teacher_id=teacher.user_id, student_id=me.user_id, score_type=ScoreType.MAJOR_SKILL,
                           item_id=major[0].item_id, content="정정", points=-3),
        MeisterScoreDetail(teacher_id=teacher.user_id, student_id=me.user_id, score_type=ScoreType.MAJOR_SKILL,
                           item_id=None, content="항목 없음", points=0),
    ])
    await db.commit()
    areas = {a["scoreType"]: a for a in (await (await make_client(me)).get(f"/api/students/{me.user_id}/meister-scores")).json()["areas"]}
    items = areas["MAJOR_SKILL"]["items"]
    assert [(i["name"], i["maxPoints"], i["earnedPoints"]) for i in items] == [
        ("국가기술자격증", 30, 12), ("대회 입상", 40, 0)]  # 합계는 감점 포함, 점수 없는 항목은 0점
    assert set(items[0]) == {"itemId", "name", "maxPoints", "earnedPoints"}
    assert all(i["earnedPoints"] == 0 for a in areas.values() if a["scoreType"] != "MAJOR_SKILL" for i in a["items"])
    assert all(len(a["items"]) == 2 for a in areas.values())
