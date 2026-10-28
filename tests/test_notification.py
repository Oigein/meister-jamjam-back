import asyncio
import json

from app.domains.notification import service
from app.domains.notification.router import event_stream
from app.domains.notification.service import hub
from app.common.enums import NotificationType
from tests.factories import make_student


async def push(db, user, n, prefix="알림"):
    for i in range(n):
        service.add(db, user.user_id, NotificationType.MEISTER_SCORE_CHANGED, f"{prefix}{i}", "본문", f"/x/{i}")
        await service.commit(db)
        await asyncio.sleep(0.002)


async def test_list_cursor_read_and_count(make_client, db):
    me, other = await make_student(db), await make_student(db, "타인")
    c, oc = await make_client(me), await make_client(other)
    await push(db, me, 5)
    await push(db, other, 1, "남의알림")

    first = (await c.get("/api/notifications", params={"size": 2})).json()
    assert [i["title"] for i in first["items"]] == ["알림4", "알림3"] and first["nextCursor"]
    second = (await c.get("/api/notifications", params={"size": 2, "cursor": first["nextCursor"]})).json()
    assert [i["title"] for i in second["items"]] == ["알림2", "알림1"]
    last = (await c.get("/api/notifications", params={"size": 2, "cursor": second["nextCursor"]})).json()
    assert [i["title"] for i in last["items"]] == ["알림0"] and last["nextCursor"] is None  # 마지막이면 null
    assert (await c.get("/api/notifications", params={"cursor": "###"})).status_code == 400
    assert len((await c.get("/api/notifications", params={"size": 500})).json()["items"]) == 5  # size 최대 50으로 제한

    item = first["items"][0]
    assert set(item) == {"notificationId", "type", "title", "body", "targetUrl", "isRead", "createdAt"}
    assert item["createdAt"].endswith("+09:00") and item["isRead"] is False

    assert (await c.get("/api/notifications/unread-count")).json() == {"count": 5}
    assert (await c.patch(f"/api/notifications/{item['notificationId']}/read")).status_code == 204
    assert (await c.patch(f"/api/notifications/{item['notificationId']}/read")).status_code == 204  # 이미 읽었어도 204
    assert (await c.get("/api/notifications/unread-count")).json() == {"count": 4}
    assert len((await c.get("/api/notifications", params={"unreadOnly": "true"})).json()["items"]) == 4
    # 다른 사람의 알림은 404
    assert (await oc.patch(f"/api/notifications/{item['notificationId']}/read")).status_code == 404
    assert (await c.patch("/api/notifications/nope/read")).status_code == 404

    assert (await oc.patch("/api/notifications/read-all")).status_code == 204
    assert (await c.get("/api/notifications/unread-count")).json() == {"count": 4}  # 남의 것은 건드리지 않는다
    assert (await c.patch("/api/notifications/read-all")).status_code == 204
    assert (await c.get("/api/notifications/unread-count")).json() == {"count": 0}
    assert (await (await make_client()).get("/api/notifications")).status_code == 401


def parse(chunk: str) -> dict:
    out = {}
    for line in chunk.strip().splitlines():
        key, _, value = line.partition(": ")
        out[key] = value
    return out


async def test_sse_stream_pushes_pings_and_replays(db):
    me = await make_student(db)
    await push(db, me, 3)
    ids = [n["notificationId"] for n in (await service.list_notifications(db, me.user_id, False, None, 10))["items"]][::-1]

    # Last-Event-ID 이후 알림을 이어서 보낸다
    stream = event_stream(me.user_id, ids[0], 0.05)
    replay = [parse(await stream.__anext__()) for _ in range(2)]
    assert [r["id"] for r in replay] == ids[1:] and all(r["event"] == "notification" for r in replay)

    # 새 알림은 커밋 직후 바로 전달되고, 없으면 ping
    assert parse(await stream.__anext__())["event"] == "ping"
    service.add(db, me.user_id, NotificationType.EVIDENCE_APPROVED, "새 알림", "본문")
    await service.commit(db)
    got = parse(await stream.__anext__())
    assert got["event"] == "notification" and json.loads(got["data"])["title"] == "새 알림"

    await stream.aclose()
    assert not hub._subs.get(me.user_id)  # 연결이 끊기면 구독을 정리한다


async def test_rollback_does_not_publish(db):
    uid = (await make_student(db)).user_id
    q = hub.subscribe(uid)
    service.add(db, uid, NotificationType.EVIDENCE_APPROVED, "t", "b")
    await db.rollback()
    assert q.empty()
    hub.unsubscribe(uid, q)
