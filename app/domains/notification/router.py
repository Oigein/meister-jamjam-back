import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.database import get_sessionmaker
from app.core.dependencies import DB, CurrentUser
from app.domains.notification import service
from app.domains.notification.service import hub, to_item

router = APIRouter(tags=["notification"])


@router.get("/notifications")
async def list_notifications(
    db: DB,
    user: CurrentUser,
    unread_only: bool = Query(False, alias="unreadOnly"),
    cursor: str | None = None,
    size: int = Query(20, ge=1),
):
    return await service.list_notifications(db, user.user_id, unread_only, cursor or None, size)


@router.get("/notifications/unread-count")
async def unread_count(db: DB, user: CurrentUser):
    return {"count": await service.unread_count(db, user.user_id)}


# read-all을 먼저 선언해 {notification_id}와 겹치지 않게 한다
@router.patch("/notifications/read-all", status_code=204)
async def read_all(db: DB, user: CurrentUser):
    await service.mark_all_read(db, user.user_id)
    return Response(status_code=204)


@router.patch("/notifications/{notification_id}/read", status_code=204)
async def read_one(notification_id: str, db: DB, user: CurrentUser):
    await service.mark_read(db, user.user_id, notification_id)
    return Response(status_code=204)


def _event(name: str, data: dict, event_id: str | None = None) -> str:
    out = ""
    if event_id:
        out += f"id: {event_id}\n"
    return out + f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def event_stream(user_id: str, last_event_id: str | None, ping_seconds: float) -> AsyncIterator[str]:
    queue = hub.subscribe(user_id)
    try:
        if last_event_id:
            async with get_sessionmaker()() as session:
                for n in await service.backlog_after(session, user_id, last_event_id):
                    yield _event("notification", to_item(n), n.notification_id)
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=ping_seconds)
                yield _event("notification", item, item["notificationId"])
            except asyncio.TimeoutError:
                yield _event("ping", {})
    finally:
        hub.unsubscribe(user_id, queue)


@router.get("/notifications/stream")
async def stream(user: CurrentUser, request: Request, last_event_id: str | None = Header(None)):
    return StreamingResponse(
        event_stream(user.user_id, last_event_id, settings.sse_ping_seconds),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
