from datetime import timedelta

from app.common.timeutil import now_kst
from tests.factories import make_admin, make_student, make_teacher


def payload(**over):
    start = now_kst() + timedelta(days=10)
    base = {"contestName": "부산 SW 해커톤", "content": "대회 안내 본문", "scope": "OUT_SCHOOL", "categoryId": 3,
            "tagIds": [1, 5], "startAt": start.isoformat() + "+09:00",
            "finishAt": (start + timedelta(days=1)).isoformat() + "+09:00"}
    base.update(over)
    return base


async def test_categories_list_and_add(make_client, db):
    t = await make_client(await make_teacher(db))
    s = await make_client(await make_student(db))
    items = (await s.get("/api/contest-categories")).json()["items"]
    assert [(c["name"], c["isDefault"]) for c in items] == [("공모전", True), ("경진대회", True), ("해커톤", True)]

    r = await t.post("/api/contest-categories", json={"name": "  아이디어톤 "})
    assert r.status_code == 201 and r.json()["created"] is True and r.json()["isDefault"] is False
    # 공백 제거 + 소문자로 같으면 같은 카테고리
    dup = await t.post("/api/contest-categories", json={"name": "해 커 톤"})
    assert dup.status_code == 200 and dup.json()["created"] is False and dup.json()["name"] == "해커톤"
    assert (await t.post("/api/contest-categories", json={"name": "아이디어톤"})).status_code == 200
    await t.post("/api/contest-categories", json={"name": "가나다"})
    names = [c["name"] for c in (await s.get("/api/contest-categories")).json()["items"]]
    assert names == ["공모전", "경진대회", "해커톤", "가나다", "아이디어톤"]  # 기본(시드 순) → 추가(가나다순)

    def reason(resp):
        return resp.json()["fieldErrors"][0]["reason"]

    assert reason(await t.post("/api/contest-categories", json={"name": "   "})) == "EMPTY"
    assert reason(await t.post("/api/contest-categories", json={"name": "가" * 21})) == "TOO_LONG"
    assert reason(await t.post("/api/contest-categories", json={"name": "<script>"})) == "INVALID_CHARACTER"
    assert (await t.post("/api/contest-categories", json={"name": "A&B (2026)-x·y"})).status_code == 201
    assert (await s.post("/api/contest-categories", json={"name": "학생"})).status_code == 403


async def test_create_update_delete_permissions(make_client, db):
    author = await make_teacher(db, "작성교사")
    other = await make_teacher(db, "다른교사")
    admin = await make_admin(db)
    a, o, ad = await make_client(author), await make_client(other), await make_client(admin)

    r = await a.post("/api/contests", json=payload())
    assert r.status_code == 201 and r.headers["location"] == f"/api/contests/{r.json()['contestId']}"
    cid = r.json()["contestId"]
    body = r.json()
    assert body["author"]["name"] == "작성교사" and body["tags"] == ["백엔드", "임베디드"] and body["isVerified"] is False
    assert body["category"] == {"categoryId": 3, "name": "해커톤"} and body["startAt"].endswith("+09:00")

    assert (await o.put(f"/api/contests/{cid}", json=payload())).status_code == 403
    assert (await o.delete(f"/api/contests/{cid}")).status_code == 403
    upd = await a.put(f"/api/contests/{cid}", json=payload(contestName="수정됨", tagIds=[2], expectedScore=5,
                                                          difficulty=3, prepHours=20, isVerified=True))
    assert upd.status_code == 200 and upd.json()["contestName"] == "수정됨" and upd.json()["tags"] == ["프론트엔드"]
    assert (upd.json()["expectedScore"], upd.json()["difficulty"], upd.json()["prepHours"], upd.json()["isVerified"]) == (5, 3, 20, True)
    assert (await ad.put(f"/api/contests/{cid}", json=payload(contestName="관리자 수정"))).status_code == 200
    assert (await (await make_client(await make_student(db))).post("/api/contests", json=payload())).status_code == 403
    assert (await a.put("/api/contests/999", json=payload())).json()["code"] == "CONTEST_NOT_FOUND"

    assert (await o.delete(f"/api/contests/{cid}")).status_code == 403
    assert (await ad.delete(f"/api/contests/{cid}")).status_code == 204
    assert (await a.get(f"/api/contests/{cid}")).status_code == 404


async def test_contest_validation(make_client, db):
    a = await make_client(await make_teacher(db))
    start = now_kst() + timedelta(days=1)
    reversed_dates = payload(startAt=(start + timedelta(days=2)).isoformat() + "+09:00",
                             finishAt=start.isoformat() + "+09:00")
    r = await a.post("/api/contests", json=reversed_dates)
    assert r.status_code == 400 and r.json()["fieldErrors"][0]["field"] == "finishAt"
    assert (await a.post("/api/contests", json=payload(categoryId=999))).json()["fieldErrors"][0]["field"] == "categoryId"
    assert (await a.post("/api/contests", json=payload(tagIds=[1, 999]))).json()["fieldErrors"][0]["field"] == "tagIds"
    assert (await a.post("/api/contests", json=payload(contestName="가" * 31))).status_code == 400
    assert (await a.post("/api/contests", json=payload(contestName=""))).status_code == 400
    assert (await a.post("/api/contests", json=payload(content=""))).status_code == 400
    assert (await a.post("/api/contests", json=payload(scope="ABROAD"))).status_code == 400
    missing_scope = payload()
    del missing_scope["scope"]
    assert (await a.post("/api/contests", json=missing_scope)).status_code == 400  # 기본값 없음
    assert (await a.post("/api/contests", json=payload(difficulty=6))).status_code == 400
    # 시작과 종료가 같은 것은 허용 (startAt ≤ finishAt)
    same = payload()
    same["finishAt"] = same["startAt"]
    assert (await a.post("/api/contests", json=same)).status_code == 201


async def test_list_ordering_filters_and_bookmarks(make_client, db):
    teacher = await make_teacher(db)
    t = await make_client(teacher)
    now = now_kst()

    def when(days):
        return (now + timedelta(days=days)).isoformat() + "+09:00"

    async def add(name, start, finish, **over):
        r = await t.post("/api/contests", json=payload(contestName=name, startAt=when(start), finishAt=when(finish), **over))
        assert r.status_code == 201, r.text
        return r.json()["contestId"]

    far = await add("먼 마감", 1, 30, scope="IN_SCHOOL", categoryId=1)
    near = await add("가까운 마감", 1, 3)
    ended_recent = await add("최근 종료", -10, -1)
    ended_old = await add("오래전 종료", -40, -30)

    student = await make_student(db)
    s = await make_client(student)
    items = (await s.get("/api/contests")).json()["items"]
    assert [i["contestName"] for i in items] == ["가까운 마감", "먼 마감", "최근 종료", "오래전 종료"]
    assert items[0]["dDay"] in (2, 3) and items[2]["dDay"] < 0 and items[0]["tags"] == ["백엔드", "임베디드"]
    assert all(i["isBookmarked"] is False for i in items)

    assert [i["contestName"] for i in (await s.get("/api/contests", params={"scope": "IN_SCHOOL"})).json()["items"]] == ["먼 마감"]
    assert (await s.get("/api/contests", params={"categoryId": 1})).json()["totalElements"] == 1
    assert (await s.get("/api/contests", params={"categoryId": 2})).json()["items"] == []
    assert (await s.get("/api/contests", params={"categoryId": 999})).status_code == 400
    assert (await s.get("/api/contests", params={"scope": "NOPE"})).status_code == 400

    # 북마크: 멱등, 학생만
    assert (await s.put(f"/api/contests/{near}/bookmark")).status_code == 204
    assert (await s.put(f"/api/contests/{near}/bookmark")).status_code == 204
    assert (await s.put(f"/api/contests/{ended_old}/bookmark")).status_code == 204
    listed = {i["contestId"]: i["isBookmarked"] for i in (await s.get("/api/contests")).json()["items"]}
    assert listed[near] is True and listed[far] is False
    assert (await s.get(f"/api/contests/{near}")).json()["isBookmarked"] is True
    mine = (await s.get("/api/me/bookmarks")).json()
    assert [i["contestName"] for i in mine["items"]] == ["가까운 마감", "오래전 종료"] and mine["totalElements"] == 2
    assert (await s.delete(f"/api/contests/{near}/bookmark")).status_code == 204
    assert (await s.delete(f"/api/contests/{near}/bookmark")).status_code == 204
    assert (await s.put("/api/contests/9999/bookmark")).status_code == 404
    assert (await t.put(f"/api/contests/{near}/bookmark")).status_code == 403  # 교사
    assert (await t.get("/api/me/bookmarks")).status_code == 403
    # 교사 화면의 isBookmarked는 항상 false
    assert all(i["isBookmarked"] is False for i in (await t.get("/api/contests")).json()["items"])

    # 삭제하면 북마크·태깅 행도 함께 삭제
    assert (await t.delete(f"/api/contests/{ended_old}")).status_code == 204
    assert (await s.get("/api/me/bookmarks")).json()["totalElements"] == 0
    from sqlalchemy import func, select
    from app.domains.contest.models import ContestTagging

    left = await db.scalar(select(func.count()).select_from(ContestTagging).where(ContestTagging.contest_id == ended_old))
    assert left == 0
    assert ended_recent and far


async def test_contest_list_pagination(make_client, db):
    t = await make_client(await make_teacher(db))
    for n in range(25):
        assert (await t.post("/api/contests", json=payload(contestName=f"대회{n}"))).status_code == 201
    r = (await t.get("/api/contests", params={"page": 2})).json()
    assert len(r["items"]) == 5 and r["totalPages"] == 2 and r["page"] == 2


async def test_academic_schedules(make_client, db):
    from datetime import date
    from app.common.enums import ScheduleType
    from app.domains.contest.models import AcademicSchedule

    db.add_all([
        AcademicSchedule(type=ScheduleType.EXAM, title="2학기 기말고사", start_date=date(2026, 12, 8), end_date=date(2026, 12, 11)),
        AcademicSchedule(type=ScheduleType.PROJECT, title="나르샤", start_date=date(2026, 11, 2), end_date=date(2026, 11, 6)),
    ])
    await db.commit()
    s = await make_client(await make_student(db))
    items = (await s.get("/api/academic-schedules", params={"from": "2026-11-01", "to": "2026-12-31"})).json()["items"]
    assert [i["title"] for i in items] == ["나르샤", "2학기 기말고사"] and items[1]["startDate"] == "2026-12-08"
    assert [i["title"] for i in (await s.get("/api/academic-schedules", params={"from": "2026-12-10"})).json()["items"]] == ["2학기 기말고사"]
    assert (await s.get("/api/academic-schedules", params={"to": "2026-11-01"})).json()["items"] == []
