from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.common.mailer import LogMailer, set_mailer
from app.common.storage import private_storage
from app.common.timeutil import now_kst
from app.core.config import settings
from app.domains.notification.models import Notification
from app.domains.report.models import SelfReport, SelfReportAttachment
from app.domains.report.service import cleanup_orphan_attachments
from tests.factories import make_admin, make_student, make_teacher

JPG = b"\xff\xd8\xff\xe0" + b"SECRET-IMAGE-BYTES" * 4
TITLE = "실습실 노트북 충전기 분실"
CONTENT = "10월 28일 5교시 후 실습실3에서 비밀 내용"


class SpyMailer:
    def __init__(self):
        self.sent = []

    async def send(self, to, subject, body):
        self.sent.append((to, subject, body))


@pytest.fixture
def mailer():
    spy = SpyMailer()
    set_mailer(spy)
    yield spy
    set_mailer(None)


@pytest.fixture
async def world(db, make_client):
    student = await make_student(db, "홍길동", 2, 1, 5)
    homeroom = await make_teacher(db, "박담임", position="2학년 1반 담임", homeroom=(2, 1))
    other = await make_teacher(db, "김상담", position="상담교사")
    admin = await make_admin(db)
    return {
        "student": student, "homeroom": homeroom, "other": other, "admin": admin,
        "s": await make_client(student), "h": await make_client(homeroom),
        "o": await make_client(other), "a": await make_client(admin),
    }


def body(w, **over):
    base = {"type": "LOST_FOUND", "title": TITLE, "content": CONTENT, "recipientIds": [w["homeroom"].user_id],
            "changeReason": None, "preferredHandling": "WRITTEN_REPLY", "attachmentIds": []}
    base.update(over)
    return base


async def create(w, **over):
    r = await w["s"].post("/api/self-reports", json=body(w, **over))
    assert r.status_code == 201, r.text
    return r.json()


async def test_default_recipient_and_fallbacks(make_client, db):
    s = await make_student(db, "학생", 3, 2, 1)
    c = await make_client(s)
    assert (await c.get("/api/self-reports/default-recipient")).json() == {
        "teacher": None, "isFallback": True, "fallbackReason": "HOMEROOM_NOT_ASSIGNED"}
    counselor = await make_teacher(db, "김상담", position="상담교사")
    r = (await c.get("/api/self-reports/default-recipient")).json()
    assert r["teacher"]["teacherId"] == counselor.user_id and r["isFallback"] is True
    head = await make_teacher(db, "이부장", position="3학년 부장")
    assert (await c.get("/api/self-reports/default-recipient")).json()["teacher"]["teacherId"] == head.user_id  # 부장 우선
    homeroom = await make_teacher(db, "최담임", homeroom=(3, 2))
    r = (await c.get("/api/self-reports/default-recipient")).json()
    assert r["isFallback"] is False and r["fallbackReason"] is None
    assert r["teacher"]["teacherId"] == homeroom.user_id and r["teacher"]["position"] == "3학년 2반 담임"
    assert (await (await make_client(homeroom)).get("/api/self-reports/default-recipient")).status_code == 403


async def test_submit_encrypts_and_notifies_without_content(world, db, mailer):
    r = await create(world)
    assert r["status"] == "UNREAD" and r["editable"] is True and r["title"] == TITLE and r["content"] == CONTENT
    assert r["student"]["name"] == "홍길동" and r["recipients"] == [
        {"teacherId": world["homeroom"].user_id, "name": "박담임", "readAt": None}]

    row = await db.scalar(select(SelfReport).where(SelfReport.report_id == r["reportId"]))
    assert row.title != TITLE and row.content != CONTENT and CONTENT not in row.content  # 암호문으로 저장

    note = (await world["h"].get("/api/notifications")).json()["items"][0]
    assert note["type"] == "SELF_REPORT_RECEIVED" and note["targetUrl"] == f"/teacher/self-reports/{r['reportId']}"
    assert "2학년 1반 홍길동 학생" in note["body"] and TITLE not in note["body"] + note["title"]
    assert mailer.sent and mailer.sent[0][0] == world["homeroom"].email
    assert TITLE not in mailer.sent[0][1] + mailer.sent[0][2] and CONTENT not in mailer.sent[0][2]


async def test_submit_validation(world, db):
    s = world["s"]
    other_student = await make_student(db, "다른학생")
    bad = [
        ({"title": ""}, 400), ({"title": "가" * 51}, 400), ({"content": ""}, 400), ({"content": "가" * 2001}, 400),
        ({"type": "NOPE"}, 400), ({"preferredHandling": "X"}, 400), ({"recipientIds": []}, 400),
        ({"attachmentIds": ["a", "b", "c", "d"]}, 400),
    ]
    for over, status in bad:
        assert (await s.post("/api/self-reports", json=body(world, **over))).status_code == status, over
    # 교사가 아닌 수신자, 없는 수신자
    r = await s.post("/api/self-reports", json=body(world, recipientIds=[other_student.user_id]))
    assert r.status_code == 400 and r.json()["code"] == "INVALID_RECIPIENT"
    assert (await s.post("/api/self-reports", json=body(world, recipientIds=["nope"]))).json()["code"] == "INVALID_RECIPIENT"
    # 수신자 수 제한(기본 1명)과 중복
    two = [world["homeroom"].user_id, world["other"].user_id]
    assert (await s.post("/api/self-reports", json=body(world, recipientIds=two))).json()["code"] == "TOO_MANY_RECIPIENTS"
    dup = await s.post("/api/self-reports", json=body(world, recipientIds=[two[0], two[0]]))
    assert dup.status_code == 400 and dup.json()["fieldErrors"][0]["reason"] == "DUPLICATE"
    settings.self_report_max_recipients = 2
    try:
        assert (await s.post("/api/self-reports", json=body(world, recipientIds=two, changeReason="COUNSELING"))).status_code == 201
    finally:
        settings.self_report_max_recipients = 1
    assert (await world["h"].post("/api/self-reports", json=body(world))).status_code == 403


async def test_attachments_encrypted_and_access_controlled(world, db):
    s = world["s"]
    up = await s.post("/api/self-reports/attachments", files={"file": ("충전기.jpg", JPG, "image/jpeg")})
    assert up.status_code == 201 and up.json()["fileName"] == "충전기.jpg" and up.json()["sizeBytes"] == len(JPG)
    att_id = up.json()["attachmentId"]
    att = await db.scalar(select(SelfReportAttachment).where(SelfReportAttachment.attachment_id == att_id))
    assert b"SECRET-IMAGE-BYTES" not in await private_storage().read(att.file_key)  # 디스크에 평문이 남지 않는다
    assert att.file_name != "충전기.jpg"

    assert (await s.post("/api/self-reports/attachments", files={"file": ("x.jpg", b"plain text", "image/jpeg")})).status_code == 415
    assert (await s.post("/api/self-reports/attachments", files={"file": ("x.jpg", b"", "image/jpeg")})).status_code == 400
    settings.self_report_attachment_bytes = 10
    try:
        assert (await s.post("/api/self-reports/attachments", files={"file": ("x.jpg", JPG, "image/jpeg")})).status_code == 413
    finally:
        settings.self_report_attachment_bytes = 10 * 1024 * 1024

    # 다른 학생의 파일, 이미 연결된 파일은 쓸 수 없다
    other = await make_client_for(world, db)
    assert (await other.post("/api/self-reports", json=body(world, attachmentIds=[att_id]))).status_code == 400
    r = await create(world, attachmentIds=[att_id])
    assert r["attachments"] == [{"attachmentId": att_id, "fileName": "충전기.jpg", "sizeBytes": len(JPG)}]
    assert (await s.post("/api/self-reports", json=body(world, attachmentIds=[att_id]))).status_code == 400

    url = f"/api/self-reports/{r['reportId']}/attachments/{att_id}"
    for who in ("s", "h"):
        f = await world[who].get(url)
        assert f.status_code == 200 and f.content == JPG and f.headers["cache-control"] == "no-store"
        assert f.headers["content-disposition"].startswith("attachment;")
    for who in ("o", "a"):
        assert (await world[who].get(url)).status_code == 404
    assert (await world["s"].get(f"/api/self-reports/{r['reportId']}/attachments/nope")).status_code == 404


async def make_client_for(world, db):
    from tests.conftest import ORIGIN  # noqa: F401
    from httpx import ASGITransport, AsyncClient
    from app.core.security import create_session
    from app.main import app

    stranger = await make_student(db, "낯선학생")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                       headers={"Origin": ORIGIN, "Cookie": f"SESSION={await create_session(stranger.user_id)}"})


async def test_privacy_everyone_else_gets_404(world, db):
    r = await create(world)
    rid = r["reportId"]
    stranger = await make_client_for(world, db)
    paths = [("get", f"/api/self-reports/{rid}"), ("get", f"/api/self-reports/{rid}/replies"),
             ("post", f"/api/self-reports/{rid}/replies"), ("patch", f"/api/self-reports/{rid}/status"),
             ("patch", f"/api/self-reports/{rid}"), ("delete", f"/api/self-reports/{rid}")]
    for who in (stranger, world["o"], world["a"]):  # 다른 학생, 수신자가 아닌 교사, 관리자
        for method, path in paths:
            payload = {"content": "x"} if "replies" in path else {"status": "DONE"} if "status" in path else {}
            resp = await getattr(who, method)(path, **({"json": payload} if method in ("post", "patch") else {}))
            assert resp.status_code in (404, 403), (method, path, resp.status_code)
            if resp.status_code == 403:
                assert method in ("patch", "delete", "post") and "self-reports/" + rid in path
    # 권한 없는 접근은 읽음 처리도 일으키지 않는다
    row = await db.scalar(select(SelfReport).where(SelfReport.report_id == rid))
    await db.refresh(row)
    assert row.status.value == "UNREAD"
    assert (await world["o"].get("/api/self-reports/not-a-uuid")).status_code == 404
    assert (await world["o"].get("/api/teacher/self-reports")).json()["items"] == []
    assert (await world["a"].get("/api/teacher/self-reports")).json()["items"] == []


async def test_teacher_open_marks_read_and_locks_edit(world, db):
    r = await create(world)
    rid = r["reportId"]
    # 수정은 확인 전에만
    edit = await world["s"].patch(f"/api/self-reports/{rid}", json={"title": "수정된 제목", "preferredHandling": "MEETING"})
    assert edit.status_code == 200 and edit.json()["title"] == "수정된 제목" and edit.json()["preferredHandling"] == "MEETING"
    assert edit.json()["content"] == CONTENT and edit.json()["status"] == "UNREAD"
    assert (await world["s"].patch(f"/api/self-reports/{rid}", json={"title": ""})).status_code == 400

    teacher_list = (await world["h"].get("/api/teacher/self-reports")).json()["items"][0]
    assert teacher_list["status"] == "UNREAD" and teacher_list["title"] == "수정된 제목" and teacher_list["student"]["number"] == 5

    d = (await world["h"].get(f"/api/self-reports/{rid}")).json()
    assert d["status"] == "READ" and d["recipients"][0]["readAt"] and d["editable"] is False
    note = (await world["s"].get("/api/notifications")).json()["items"][0]
    assert note["type"] == "SELF_REPORT_STATUS_CHANGED" and note["targetUrl"] == f"/me/self-reports/{rid}"
    assert "수정된 제목" not in note["body"]

    locked = await world["s"].patch(f"/api/self-reports/{rid}", json={"title": "또 수정"})
    assert locked.status_code == 409 and locked.json()["code"] == "REPORT_ALREADY_READ"
    assert (await world["s"].delete(f"/api/self-reports/{rid}")).json()["code"] == "REPORT_ALREADY_READ"
    assert (await world["s"].get(f"/api/self-reports/{rid}")).json()["editable"] is False
    # 두 번째로 열어도 상태 알림은 늘지 않는다
    await world["h"].get(f"/api/self-reports/{rid}")
    n = await db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == world["student"].user_id))
    assert n == 1


async def test_edit_recipients_and_attachments(world, db):
    s = world["s"]
    a1 = (await s.post("/api/self-reports/attachments", files={"file": ("1.jpg", JPG, "image/jpeg")})).json()["attachmentId"]
    a2 = (await s.post("/api/self-reports/attachments", files={"file": ("2.jpg", JPG, "image/jpeg")})).json()["attachmentId"]
    r = await create(world, attachmentIds=[a1])
    rid = r["reportId"]
    out = (await s.patch(f"/api/self-reports/{rid}", json={"recipientIds": [world["other"].user_id],
                                                           "changeReason": "COUNSELING", "attachmentIds": [a2]})).json()
    assert out["recipients"][0]["name"] == "김상담" and out["changeReason"] == "COUNSELING"
    assert [a["attachmentId"] for a in out["attachments"]] == [a2]
    assert await db.scalar(select(SelfReportAttachment).where(SelfReportAttachment.attachment_id == a1)) is None
    # null로 changeReason 제거
    assert (await s.patch(f"/api/self-reports/{rid}", json={"changeReason": None})).json()["changeReason"] is None
    # 변경 전 수신자는 더 이상 볼 수 없다
    assert (await world["h"].get(f"/api/self-reports/{rid}")).status_code == 404
    assert (await world["o"].get(f"/api/self-reports/{rid}")).status_code == 200


async def test_withdraw_removes_everything(world, db):
    s = world["s"]
    att = (await s.post("/api/self-reports/attachments", files={"file": ("1.jpg", JPG, "image/jpeg")})).json()["attachmentId"]
    r = await create(world, attachmentIds=[att])
    key = (await db.scalar(select(SelfReportAttachment).where(SelfReportAttachment.attachment_id == att))).file_key
    assert (await world["h"].get("/api/notifications/unread-count")).json() == {"count": 1}
    assert (await s.delete(f"/api/self-reports/{r['reportId']}")).status_code == 204
    assert (await s.get(f"/api/self-reports/{r['reportId']}")).status_code == 404
    assert (await world["h"].get("/api/notifications/unread-count")).json() == {"count": 0}  # 수신 교사 알림도 제거
    with pytest.raises(FileNotFoundError):
        await private_storage().read(key)
    assert (await s.get("/api/me/self-reports")).json()["items"] == []


async def test_status_transitions(world):
    r = await create(world)
    rid, h = r["reportId"], world["h"]
    # 확인하기 전에는 상태를 바꿀 수 없다 (UNREAD → 무엇이든 불가)
    assert (await h.patch(f"/api/self-reports/{rid}/status", json={"status": "DONE"})).json()["code"] == "INVALID_STATUS_TRANSITION"
    await h.get(f"/api/self-reports/{rid}")
    assert (await h.patch(f"/api/self-reports/{rid}/status", json={"status": "UNREAD"})).status_code == 409
    assert (await h.patch(f"/api/self-reports/{rid}/status", json={"status": "READ"})).status_code == 409
    assert (await h.patch(f"/api/self-reports/{rid}/status", json={"status": "BOGUS"})).status_code == 400
    ok = await h.patch(f"/api/self-reports/{rid}/status", json={"status": "IN_PROGRESS"})
    assert ok.status_code == 200 and ok.json()["status"] == "IN_PROGRESS"
    assert (await h.patch(f"/api/self-reports/{rid}/status", json={"status": "IN_PROGRESS"})).status_code == 409
    assert (await h.patch(f"/api/self-reports/{rid}/status", json={"status": "DONE"})).json()["status"] == "DONE"
    assert (await h.patch(f"/api/self-reports/{rid}/status", json={"status": "DONE"})).status_code == 409  # 되돌리기 불가
    assert (await world["s"].patch(f"/api/self-reports/{rid}/status", json={"status": "DONE"})).status_code == 403
    notes = (await world["s"].get("/api/notifications")).json()["items"]
    assert [n["body"] for n in notes][:2] == ["자진 신고 처리가 완료되었습니다.", "자진 신고를 선생님이 처리 중입니다."]


async def test_read_to_done_directly(world):
    rid = (await create(world))["reportId"]
    await world["h"].get(f"/api/self-reports/{rid}")
    assert (await world["h"].patch(f"/api/self-reports/{rid}/status", json={"status": "DONE"})).json()["status"] == "DONE"


async def test_replies_flow_auto_in_progress_and_new_reply_flags(world, db):
    rid = (await create(world))["reportId"]
    s, h = world["s"], world["h"]
    assert (await s.post(f"/api/self-reports/{rid}/replies", json={"content": ""})).status_code == 400
    assert (await s.post(f"/api/self-reports/{rid}/replies", json={"content": "가" * 1001})).status_code == 400

    first = await h.post(f"/api/self-reports/{rid}/replies", json={"content": "내일 점심시간에 교무실로 와 주세요."})
    assert first.status_code == 201 and first.json()["author"] == {"userId": world["homeroom"].user_id, "name": "박담임", "role": "TEACHER"}
    # 교사가 처음 답변하면 자동으로 처리 중
    assert (await h.get(f"/api/self-reports/{rid}")).json()["status"] == "IN_PROGRESS"
    row = await db.scalar(select(SelfReport).where(SelfReport.report_id == rid))
    assert "교무실" not in row.title + row.content
    from app.domains.report.models import SelfReportReply

    assert "교무실" not in (await db.scalar(select(SelfReportReply.content)))  # 답변도 암호화

    # 학생에게 새 답변 표시 → 목록을 열어보면 사라진다
    assert (await s.get("/api/me/self-reports")).json()["items"][0]["hasNewReply"] is True
    note = (await s.get("/api/notifications")).json()["items"][0]
    assert note["type"] == "SELF_REPORT_REPLIED" and "교무실" not in note["body"]
    replies = (await s.get(f"/api/self-reports/{rid}/replies")).json()["items"]
    assert [r["content"] for r in replies] == ["내일 점심시간에 교무실로 와 주세요."]
    assert (await s.get("/api/me/self-reports")).json()["items"][0]["hasNewReply"] is False

    # 학생의 답변 → 교사에게 알림·표시
    await s.post(f"/api/self-reports/{rid}/replies", json={"content": "네 알겠습니다."})
    assert (await h.get("/api/teacher/self-reports")).json()["items"][0]["hasNewReply"] is True
    assert (await h.get("/api/notifications")).json()["items"][0]["type"] == "SELF_REPORT_REPLIED"
    assert [r["content"] for r in (await h.get(f"/api/self-reports/{rid}/replies")).json()["items"]] == [
        "내일 점심시간에 교무실로 와 주세요.", "네 알겠습니다."]
    assert (await h.get("/api/teacher/self-reports")).json()["items"][0]["hasNewReply"] is False

    # 처리 완료 후에는 답변 불가
    await h.patch(f"/api/self-reports/{rid}/status", json={"status": "DONE"})
    closed = await s.post(f"/api/self-reports/{rid}/replies", json={"content": "추가"})
    assert closed.status_code == 409 and closed.json()["code"] == "REPORT_CLOSED"


async def test_teacher_first_reply_on_unread_goes_to_in_progress(world):
    rid = (await create(world))["reportId"]
    await world["h"].post(f"/api/self-reports/{rid}/replies", json={"content": "확인했습니다"})
    d = (await world["h"].get(f"/api/self-reports/{rid}")).json()
    assert d["status"] == "IN_PROGRESS" and d["recipients"][0]["readAt"]


async def test_lists_filters_and_sorting(world, db):
    r1 = await create(world, title="첫번째")
    r2 = await create(world, title="두번째")
    await world["h"].get(f"/api/self-reports/{r2['reportId']}")  # 두번째만 확인
    mine = (await world["s"].get("/api/me/self-reports")).json()
    assert mine["totalElements"] == 2 and mine["items"][0]["recipients"] == ["박담임"]
    assert (await world["s"].get("/api/me/self-reports", params={"status": "READ"})).json()["items"][0]["title"] == "두번째"
    got = (await world["h"].get("/api/teacher/self-reports")).json()["items"]
    assert [i["title"] for i in got] == ["첫번째", "두번째"]  # 확인 전이 먼저
    assert got[0]["preferredHandling"] == "WRITTEN_REPLY"
    assert (await world["h"].get("/api/teacher/self-reports", params={"status": "UNREAD"})).json()["totalElements"] == 1
    assert (await world["s"].get("/api/teacher/self-reports")).status_code == 403
    assert (await world["h"].get("/api/me/self-reports")).status_code == 403
    assert r1


async def test_cleanup_orphan_attachments(world, db):
    s = world["s"]
    old = (await s.post("/api/self-reports/attachments", files={"file": ("1.jpg", JPG, "image/jpeg")})).json()["attachmentId"]
    fresh = (await s.post("/api/self-reports/attachments", files={"file": ("2.jpg", JPG, "image/jpeg")})).json()["attachmentId"]
    linked = (await s.post("/api/self-reports/attachments", files={"file": ("3.jpg", JPG, "image/jpeg")})).json()["attachmentId"]
    await create(world, attachmentIds=[linked])
    for aid in (old, linked):
        att = await db.scalar(select(SelfReportAttachment).where(SelfReportAttachment.attachment_id == aid))
        att.created_at = now_kst() - timedelta(hours=25)
    await db.commit()
    assert await cleanup_orphan_attachments(db) == 1  # 24시간 안에 연결되지 않은 파일만
    remaining = set((await db.scalars(select(SelfReportAttachment.attachment_id))).all())
    assert remaining == {fresh, linked}
