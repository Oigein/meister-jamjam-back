import pytest
from sqlalchemy import select

from app.common.enums import ScoreType
from app.core.config import settings
from app.domains.merit.analyzer import DisabledAnalyzer, set_analyzer
from app.domains.merit.models import MeisterScoreItem
from app.domains.notification.models import Notification
from app.domains.user.models import Student
from tests.factories import make_student, make_teacher

JPG = b"\xff\xd8\xff\xe0" + b"0" * 64
PDF = b"%PDF-1.4\n" + b"0" * 64


class FakeAnalyzer:
    def __init__(self, item_id):
        self.item_id = item_id

    async def analyze(self, *, file_bytes, content_type, title, hint, items):
        return {
            "extracted": {"kind": "CERTIFICATE", "name": title, "issuer": "한국산업인력공단", "award": None,
                          "achievedAt": "2026-09-10"},
            "recommendation": {"scoreType": "MAJOR_SKILL", "itemId": self.item_id, "itemName": "국가기술자격증",
                               "expectedPoints": 10, "reason": "기능사 등급"},
        }


@pytest.fixture(autouse=True)
def _analyzer_reset():
    set_analyzer(DisabledAnalyzer())
    yield
    set_analyzer(DisabledAnalyzer())


async def major_item(db):
    return await db.scalar(select(MeisterScoreItem).where(MeisterScoreItem.score_type == ScoreType.MAJOR_SKILL,
                                                           MeisterScoreItem.name == "국가기술자격증"))


async def submit(client, title="정보처리기능사", data=JPG, name="자격증.jpg", **form):
    return await client.post("/api/evidences", data={"title": title, **form},
                             files={"file": (name, data, "application/octet-stream")})


async def test_submit_validation_and_file_sniffing(make_client, db):
    student = await make_student(db)
    c = await make_client(student)
    ok = await submit(c)
    assert ok.status_code == 201
    body = ok.json()
    assert body["status"] == "PENDING" and body["analysisStatus"] == "PROCESSING" and body["title"] == "정보처리기능사"

    # 확장자가 아니라 내용으로 판별한다
    fake = await submit(c, data=b"<html>not an image</html>", name="evil.jpg")
    assert fake.status_code == 415 and fake.json()["code"] == "UNSUPPORTED_FILE_TYPE"
    assert (await submit(c, data=PDF, name="x.exe")).status_code == 201
    assert (await submit(c, data=b"")).status_code == 400

    settings.evidence_max_bytes = 100
    try:
        r = await submit(c, data=JPG + b"0" * 100)
        assert r.status_code == 413 and r.json()["code"] == "FILE_TOO_LARGE"
    finally:
        settings.evidence_max_bytes = 10 * 1024 * 1024

    assert (await submit(c, title="")).status_code == 400
    assert (await submit(c, title="가" * 51)).status_code == 400
    assert (await submit(c, scoreType="NOPE")).status_code == 400
    assert (await submit(c, description="가" * 201)).status_code == 400
    assert (await c.post("/api/evidences", data={"title": "x"})).status_code == 400  # file 없음

    teacher = await make_client(await make_teacher(db))
    assert (await submit(teacher)).status_code == 403
    assert (await submit(await make_client())).status_code == 401


async def test_submit_rate_limit(make_client, db):
    c = await make_client(await make_student(db))
    for _ in range(settings.rate_upload_per_min):
        assert (await submit(c)).status_code == 201
    assert (await submit(c)).status_code == 429


async def test_analysis_runs_in_background_and_default_is_failed(make_client, db):
    student = await make_student(db)
    teacher = await make_teacher(db)
    item = await major_item(db)
    c, t = await make_client(student), await make_client(teacher)

    eid = (await submit(c)).json()["evidenceId"]
    detail = (await t.get(f"/api/evidences/{eid}")).json()
    assert detail["aiAnalysis"]["status"] == "FAILED"  # 분석기가 설정되지 않음 → 교사가 직접 판단

    set_analyzer(FakeAnalyzer(item.item_id))
    r = await t.post(f"/api/evidences/{eid}/analysis")
    assert r.status_code == 202 and r.json() == {"analysisStatus": "PROCESSING"}
    detail = (await t.get(f"/api/evidences/{eid}")).json()
    assert detail["aiAnalysis"]["status"] == "DONE"
    assert detail["aiAnalysis"]["recommendation"]["expectedPoints"] == 10
    assert detail["aiAnalysis"]["extracted"]["issuer"] == "한국산업인력공단"
    assert detail["student"]["name"] == "홍길동" and detail["review"] is None
    assert detail["file"] == {"fileName": "자격증.jpg", "contentType": "image/jpeg", "url": f"/api/evidences/{eid}/file"}


async def test_visibility_and_file_download(make_client, db):
    owner, other = await make_student(db, "주인"), await make_student(db, "타인")
    teacher = await make_teacher(db)
    eid = (await submit(await make_client(owner))).json()["evidenceId"]

    o, x, t = await make_client(owner), await make_client(other), await make_client(teacher)
    for path in (f"/api/evidences/{eid}", f"/api/evidences/{eid}/file"):
        assert (await x.get(path)).status_code == 404  # 존재 여부도 숨긴다
        assert (await o.get(path)).status_code == 200
        assert (await t.get(path)).status_code == 200
    f = await t.get(f"/api/evidences/{eid}/file")
    assert f.content == JPG and f.headers["content-type"] == "image/jpeg"
    assert f.headers["content-disposition"].startswith("inline;")
    assert (await t.get("/api/evidences/not-a-uuid")).status_code == 404
    assert (await x.post(f"/api/evidences/{eid}/approve", json={})).status_code == 403


async def test_approve_updates_score_history_notification(make_client, db):
    student, teacher = await make_student(db, "학생"), await make_teacher(db, "박선생")
    item = await major_item(db)
    s, t = await make_client(student), await make_client(teacher)
    eid = (await submit(s)).json()["evidenceId"]

    body = {"scoreType": "MAJOR_SKILL", "itemId": item.item_id, "points": 10, "content": "정보처리기능사 취득"}
    r = await t.post(f"/api/evidences/{eid}/approve", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "APPROVED" and out["scoreDetail"]["points"] == 10
    assert out["studentScore"] == {"scoreType": "MAJOR_SKILL", "rawScore": 10, "totalScore": 10}

    st = await db.get(Student, student.user_id)
    await db.refresh(st)
    assert st.major_skill_point == 10

    detail = (await t.get(f"/api/evidences/{eid}")).json()
    assert detail["status"] == "APPROVED"
    assert detail["review"]["teacher"]["name"] == "박선생" and detail["review"]["detailId"] == out["scoreDetail"]["detailId"]

    hist = (await s.get(f"/api/students/{student.user_id}/meister-scores/history")).json()["items"][0]
    assert hist["evidence"]["evidenceId"] == eid and hist["itemName"] == "국가기술자격증"

    notes = (await s.get("/api/notifications")).json()["items"]
    assert notes[0]["type"] == "EVIDENCE_APPROVED" and "+10점" in notes[0]["body"] and "전공직무능력" in notes[0]["body"]
    assert notes[0]["targetUrl"].endswith(f"detailId={out['scoreDetail']['detailId']}")
    assert (await s.get("/api/notifications/unread-count")).json() == {"count": 1}

    mine = (await s.get("/api/me/evidences")).json()["items"][0]
    assert mine["status"] == "APPROVED" and mine["approvedPoints"] == 10 and mine["reviewedAt"]

    # 이미 처리된 증빙
    again = await t.post(f"/api/evidences/{eid}/approve", json=body)
    assert again.status_code == 409 and again.json()["code"] == "EVIDENCE_ALREADY_REVIEWED"
    assert (await t.post(f"/api/evidences/{eid}/reject", json={"reason": "x"})).status_code == 409
    assert (await t.post(f"/api/evidences/{eid}/analysis")).status_code == 409


async def test_approve_limits_duplicates_and_validation(make_client, db):
    student, teacher = await make_student(db), await make_teacher(db)
    item = await major_item(db)  # 최대 30점
    s, t = await make_client(student), await make_client(teacher)

    def body(points, content="정보처리기능사 취득", **over):
        return {"scoreType": "MAJOR_SKILL", "itemId": item.item_id, "points": points, "content": content, **over}

    e1 = (await submit(s)).json()["evidenceId"]
    e2 = (await submit(s, title="두번째")).json()["evidenceId"]
    e3 = (await submit(s, title="세번째")).json()["evidenceId"]
    assert (await t.post(f"/api/evidences/{e1}/approve", json=body(20))).status_code == 200

    # 최대 인정 점수(기존 획득분 포함) 초과 → 남은 한도 안내, 상태는 그대로
    over = await t.post(f"/api/evidences/{e2}/approve", json=body(11, "다른 실적"))
    assert over.status_code == 400 and over.json()["code"] == "EXCEEDS_MAX_POINTS" and over.json()["remainingPoints"] == 10
    assert (await t.get(f"/api/evidences/{e2}")).json()["status"] == "PENDING"
    st = await db.get(Student, student.user_id)
    await db.refresh(st)
    assert st.major_skill_point == 20  # 실패한 승인은 점수를 바꾸지 않는다

    dup = await t.post(f"/api/evidences/{e2}/approve", json=body(5, " 정보처리기능사  취득 "))
    assert dup.status_code == 409 and dup.json()["code"] == "DUPLICATE_ACHIEVEMENT" and dup.json()["detailId"]
    assert (await t.post(f"/api/evidences/{e2}/approve", json=body(10, "다른 실적"))).status_code == 200

    # 입력 검증
    assert (await t.post(f"/api/evidences/{e3}/approve", json=body(0))).status_code == 400
    assert (await t.post(f"/api/evidences/{e3}/approve", json=body(1, ""))).status_code == 400
    assert (await t.post(f"/api/evidences/{e3}/approve", json=body(1, "가" * 51))).status_code == 400
    mismatch = await t.post(f"/api/evidences/{e3}/approve", json=body(1, "x", scoreType="JOB_BASIC"))
    assert mismatch.status_code == 400 and mismatch.json()["fieldErrors"][0]["field"] == "scoreType"
    assert (await t.post(f"/api/evidences/{e3}/approve", json=body(1, "x", itemId=9999))).status_code == 404
    assert (await t.post("/api/evidences/00000000-0000-4000-8000-000000000000/approve", json=body(1))).status_code == 404


async def test_duplicate_suspect_hint(make_client, db):
    student, teacher = await make_student(db), await make_teacher(db)
    item = await major_item(db)
    set_analyzer(FakeAnalyzer(item.item_id))
    s, t = await make_client(student), await make_client(teacher)
    e1 = (await submit(s, title="정보처리기능사")).json()["evidenceId"]
    await t.post(f"/api/evidences/{e1}/approve", json={"scoreType": "MAJOR_SKILL", "itemId": item.item_id,
                                                      "points": 10, "content": "정보처리기능사 취득"})
    e2 = (await submit(s, title="정보처리기능사")).json()["evidenceId"]
    suspect = (await t.get(f"/api/evidences/{e2}")).json()["aiAnalysis"]["duplicateSuspect"]
    assert suspect["content"] == "정보처리기능사 취득" and suspect["detailId"]
    assert (await t.get(f"/api/evidences/{e1}")).json()["aiAnalysis"]["duplicateSuspect"] is None


async def test_reject_flow(make_client, db):
    student, teacher = await make_student(db), await make_teacher(db)
    s, t = await make_client(student), await make_client(teacher)
    eid = (await submit(s)).json()["evidenceId"]
    assert (await t.post(f"/api/evidences/{eid}/reject", json={})).status_code == 400
    assert (await t.post(f"/api/evidences/{eid}/reject", json={"reason": "가" * 201})).status_code == 400
    r = await t.post(f"/api/evidences/{eid}/reject", json={"reason": "취득 날짜가 확인되지 않습니다."})
    assert r.json() == {"evidenceId": eid, "status": "REJECTED", "rejectReason": "취득 날짜가 확인되지 않습니다."}
    note = (await s.get("/api/notifications")).json()["items"][0]
    assert note["type"] == "EVIDENCE_REJECTED" and "취득 날짜가 확인되지 않습니다." in note["body"]
    assert note["targetUrl"] == f"/me/evidences/{eid}"
    mine = (await s.get("/api/me/evidences", params={"status": "REJECTED"})).json()["items"][0]
    assert mine["rejectReason"] == "취득 날짜가 확인되지 않습니다."
    st = await db.get(Student, student.user_id)
    await db.refresh(st)
    assert st.total_score == 0
    long = (await submit(s, title="가" * 50)).json()["evidenceId"]
    await t.post(f"/api/evidences/{long}/reject", json={"reason": "나" * 200})
    assert len((await db.scalars(select(Notification).order_by(Notification.created_at.desc()))).first().body) <= 255


async def test_direct_grant(make_client, db):
    student, teacher = await make_student(db), await make_teacher(db)
    ethic = await db.scalar(select(MeisterScoreItem).where(MeisterScoreItem.score_type == ScoreType.CHARACTER_JOB_ETHIC))
    s, t = await make_client(student), await make_client(teacher)

    def body(points, content="교내 봉사활동 리더", **over):
        return {"studentId": student.user_id, "scoreType": "CHARACTER_JOB_ETHIC", "itemId": ethic.item_id,
                "points": points, "content": content, **over}

    r = await t.post("/api/meister-scores", json=body(5))
    assert r.status_code == 201 and r.json()["studentScore"]["rawScore"] == 5
    note = (await s.get("/api/notifications")).json()["items"][0]
    assert note["type"] == "MEISTER_SCORE_CHANGED" and "+5점" in note["body"]

    assert (await t.post("/api/meister-scores", json=body(5))).json()["code"] == "DUPLICATE_ACHIEVEMENT"
    assert (await t.post("/api/meister-scores", json=body(ethic.max_points))).json()["remainingPoints"] == ethic.max_points - 5
    assert (await t.post("/api/meister-scores", json=body(0))).status_code == 400
    # 감점(정정)은 허용하되 0점 미만은 불가
    fix = await t.post("/api/meister-scores", json=body(-2, "정정"))
    assert fix.status_code == 201 and fix.json()["studentScore"]["rawScore"] == 3
    below = await t.post("/api/meister-scores", json=body(-4, "과한 정정"))
    assert below.status_code == 400 and below.json()["code"] == "SCORE_BELOW_ZERO"
    assert (await t.post("/api/meister-scores", json=body(1, "x", studentId="nope"))).status_code == 404
    assert (await s.post("/api/meister-scores", json=body(1))).status_code == 403
    # 감점 이후 남은 한도가 다시 늘어난다 (획득 점수 합 기준)
    st = await db.get(Student, student.user_id)
    await db.refresh(st)
    assert st.character_job_ethic_point == 3


async def test_teacher_endpoints(make_client, db):
    a = await make_student(db, "김하나", 2, 1, 1)
    b = await make_student(db, "이둘", 2, 1, 2)
    c = await make_student(db, "박셋", 3, 2, 1)
    teacher = await make_teacher(db, "교사")
    t = await make_client(teacher)
    await submit(await make_client(a))
    await submit(await make_client(a), title="둘째")
    eb = (await submit(await make_client(b))).json()["evidenceId"]

    found = (await t.get("/api/teacher/students", params={"q": "김", "grade": "", "classNo": "", "number": ""})).json()
    assert [(i["name"], i["pendingEvidenceCount"]) for i in found["items"]] == [("김하나", 2)]
    assert (await t.get("/api/teacher/students", params={"grade": 2, "classNo": 1, "number": 2})).json()["items"][0]["name"] == "이둘"
    assert (await t.get("/api/teacher/students", params={"grade": "x"})).status_code == 400
    assert (await t.get("/api/teacher/students")).json()["totalElements"] == 3
    assert (await (await make_client(a)).get("/api/teacher/students")).status_code == 403

    pending = (await t.get("/api/teacher/evidences")).json()
    assert pending["totalElements"] == 3 and pending["items"][0]["title"] == "정보처리기능사"  # 오래된 순
    assert pending["items"][0]["student"]["number"] == 1 and pending["items"][0]["analysisStatus"] == "FAILED"
    await t.post(f"/api/evidences/{eb}/reject", json={"reason": "사유"})
    assert (await t.get("/api/teacher/evidences")).json()["totalElements"] == 2
    assert (await t.get("/api/teacher/evidences", params={"studentId": b.user_id})).json()["totalElements"] == 1
    assert (await t.get("/api/teacher/evidences", params={"status": "REJECTED"})).json()["totalElements"] == 1

    item = await major_item(db)
    for who, pts in ((a, 5), (c, 7)):
        await t.post("/api/meister-scores", json={"studentId": who.user_id, "scoreType": "MAJOR_SKILL",
                                                  "itemId": item.item_id, "points": pts, "content": "실적"})
    other = await make_client(await make_teacher(db, "다른교사"))
    await other.post("/api/meister-scores", json={"studentId": a.user_id, "scoreType": "MAJOR_SKILL",
                                                  "itemId": item.item_id, "points": 3, "content": "또 다른 실적"})
    allh = (await t.get("/api/teacher/meister-scores")).json()
    assert allh["totalElements"] == 3 and allh["items"][0]["student"]["name"] == "김하나"
    assert allh["items"][0]["itemName"] == "국가기술자격증" and allh["items"][0]["evidenceId"] is None
    assert (await t.get("/api/teacher/meister-scores", params={"teacherId": "me"})).json()["totalElements"] == 2
    assert (await t.get("/api/teacher/meister-scores", params={"studentId": c.user_id})).json()["totalElements"] == 1
    assert (await t.get("/api/teacher/meister-scores", params={"scoreType": "JOB_BASIC"})).json()["totalElements"] == 0
    assert (await t.get("/api/teacher/meister-scores", params={"from": "2999-01-01"})).json()["totalElements"] == 0
    assert (await t.get("/api/teacher/meister-scores", params={"from": "2000-01-01", "to": "2999-01-01"})).json()["totalElements"] == 3
