from app.core.config import settings
from app.domains.mileage.models import PointRule
from tests.factories import make_student, make_teacher


async def test_point_rules_sorting_filters_and_categories(make_client, db):
    db.add(PointRule(type="DEMERIT", category="생활", title="폐지된 기준", points=9, is_active=False))
    await db.commit()
    cl = await make_client(await make_student(db))
    r = (await cl.get("/api/point-rules")).json()
    assert r["total"] == 4 and r["categories"] == ["기숙사", "봉사", "생활", "학습"]
    # 상점 → 벌점, 분류, 점수 큰 순. 폐지된 기준은 제외
    assert [i["title"] for i in r["items"]] == ["교내 봉사활동", "학업 우수", "점호 불참", "지각"]
    assert r["items"][0] == {"ruleId": r["items"][0]["ruleId"], "type": "MERIT", "category": "봉사",
                             "title": "교내 봉사활동", "points": 3, "description": "담당 교사가 확인한 교내 봉사활동 1회",
                             "note": "하루 1회만 인정"}

    only_demerit = (await cl.get("/api/point-rules", params={"type": "DEMERIT"})).json()
    assert only_demerit["total"] == 2 and only_demerit["categories"] == r["categories"]
    bogus = (await cl.get("/api/point-rules", params={"type": "WHATEVER"})).json()
    assert bogus["total"] == 4  # 허용되지 않은 type은 무시하고 전체 조회
    multi = (await cl.get("/api/point-rules", params=[("category", "생활"), ("category", "봉사")])).json()
    assert {i["category"] for i in multi["items"]} == {"생활", "봉사"}
    assert (await cl.get("/api/point-rules", params={"q": "  지각 "})).json()["total"] == 1
    assert (await cl.get("/api/point-rules", params={"q": "조회 시작"})).json()["total"] == 1  # 세부 기준도 검색
    assert (await cl.get("/api/point-rules", params={"q": "%"})).json()["total"] == 0  # LIKE 와일드카드 이스케이프
    assert (await cl.get("/api/point-rules", params={"q": "없는기준"})).json() == {
        "total": 0, "categories": r["categories"], "items": []}


async def test_point_rules_etag_and_rate_limit(make_client, db):
    cl = await make_client(await make_student(db))
    r = await cl.get("/api/point-rules")
    etag = r.headers["etag"]
    assert r.headers["cache-control"] == "no-cache" and etag
    assert (await cl.get("/api/point-rules", headers={"If-None-Match": etag})).status_code == 304
    assert (await cl.get("/api/point-rules", headers={"If-None-Match": '"stale"'})).status_code == 200
    assert (await (await make_client()).get("/api/point-rules")).status_code == 401

    for _ in range(settings.rate_point_rules_per_min):
        await cl.get("/api/point-rules")
    limited = await cl.get("/api/point-rules")
    assert limited.status_code == 429 and "retry-after" in limited.headers


async def test_grant_and_view_merit_points(make_client, db):
    student = await make_student(db, "학생")
    t1 = await make_teacher(db, "박선생")
    t2 = await make_teacher(db, "최선생")
    c1, c2 = await make_client(t1), await make_client(t2)
    rules = (await c1.get("/api/point-rules")).json()["items"]
    late = next(r for r in rules if r["title"] == "지각")

    r = await c1.post("/api/merit-points", json={"studentId": student.user_id, "type": "MERIT",
                                                 "title": "봉사활동", "content": "기숙사 환경 정리", "points": 3})
    assert r.status_code == 201 and r.json()["points"] == 3 and r.json()["type"] == "MERIT"
    r = await c2.post("/api/merit-points", json={"studentId": student.user_id, "type": "DEMERIT",
                                                 "ruleId": late["ruleId"], "title": "지각", "points": 1})
    assert r.status_code == 201 and r.json()["points"] == 1 and r.json()["type"] == "DEMERIT"

    from app.domains.user.models import Student

    await db.refresh(await db.get(Student, student.user_id))
    assert (await db.get(Student, student.user_id)).total_merit_points == 2

    me = await make_client(student)
    body = (await me.get(f"/api/students/{student.user_id}/merit-points")).json()
    assert (body["meritTotal"], body["demeritTotal"], body["net"]) == (3, 1, 2)
    assert [m["title"] for m in body["merits"]] == ["봉사활동"] and body["demerits"][0]["points"] == 1
    assert body["demerits"][0]["teacher"]["name"] == "최선생"

    grouped = (await me.get(f"/api/students/{student.user_id}/merit-points", params={"groupBy": "teacher"})).json()
    by = {g["teacher"]["name"]: g for g in grouped["byTeacher"]}
    assert (by["박선생"]["meritTotal"], by["박선생"]["demeritTotal"]) == (3, 0)
    assert by["최선생"]["items"][0]["type"] == "DEMERIT"
    assert (await me.get(f"/api/students/{student.user_id}/merit-points", params={"groupBy": "x"})).status_code == 400
    # 교사는 학생의 내역을 볼 수 있다
    assert (await c1.get(f"/api/students/{student.user_id}/merit-points")).status_code == 200


async def test_merit_points_access_and_empty(make_client, db):
    a, b = await make_student(db, "a"), await make_student(db, "b")
    cl = await make_client(a)
    r = await cl.get(f"/api/students/{b.user_id}/merit-points")
    assert r.status_code == 403
    empty = (await cl.get(f"/api/students/{a.user_id}/merit-points")).json()
    assert empty == {"studentId": a.user_id, "meritTotal": 0, "demeritTotal": 0, "net": 0, "merits": [], "demerits": []}
    t = await make_client(await make_teacher(db))
    assert (await t.get("/api/students/00000000-0000-4000-8000-000000000000/merit-points")).status_code == 404


async def test_grant_validation(make_client, db):
    s = await make_student(db)
    t = await make_client(await make_teacher(db))
    base = {"studentId": s.user_id, "type": "MERIT", "title": "봉사", "points": 1}
    assert (await t.post("/api/merit-points", json={**base, "points": 0})).status_code == 400
    assert (await t.post("/api/merit-points", json={**base, "title": "가" * 21})).status_code == 400
    assert (await t.post("/api/merit-points", json={**base, "content": "가" * 51})).status_code == 400
    assert (await t.post("/api/merit-points", json={**base, "studentId": "x"})).json()["code"] == "STUDENT_NOT_FOUND"
    assert (await t.post("/api/merit-points", json={**base, "ruleId": 9999})).json()["code"] == "RULE_NOT_FOUND"
    rules = (await t.get("/api/point-rules", params={"type": "DEMERIT"})).json()["items"]
    mismatch = await t.post("/api/merit-points", json={**base, "ruleId": rules[0]["ruleId"]})
    assert mismatch.status_code == 400 and mismatch.json()["fieldErrors"][0]["reason"] == "TYPE_MISMATCH"
    student_client = await make_client(s)
    assert (await student_client.post("/api/merit-points", json=base)).status_code == 403
