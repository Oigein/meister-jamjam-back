import asyncio
import base64
from collections import defaultdict

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import NotificationType
from app.common.exceptions import not_found, validation_failed, field_error
from app.common.ids import new_id
from app.common.timeutil import now_kst, to_iso
from app.core.config import settings
from app.domains.notification.models import Notification


def to_item(n: Notification) -> dict:
    return {
        "notificationId": n.notification_id,
        "type": n.type.value if hasattr(n.type, "value") else n.type,
        "title": n.title,
        "body": n.body,
        "targetUrl": n.target_url,
        "isRead": n.is_read,
        "createdAt": to_iso(n.created_at),
    }


class NotificationHub:
    """접속 중인 SSE 연결로 알림을 전달한다. (프로세스 단위. 여러 서버면 Redis pub/sub로 교체)"""

    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, user_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs[user_id].add(q)
        return q

    def unsubscribe(self, user_id: str, q: asyncio.Queue) -> None:
        self._subs[user_id].discard(q)
        if not self._subs[user_id]:
            self._subs.pop(user_id, None)

    def publish(self, user_id: str, item: dict) -> None:
        for q in list(self._subs.get(user_id, ())):
            q.put_nowait(item)


hub = NotificationHub()


def add(
    db: AsyncSession,
    user_id: str,
    type_: NotificationType,
    title: str,
    body: str,
    target_url: str | None = None,
) -> Notification:
    """원인이 된 처리와 같은 트랜잭션에 알림을 저장한다. 커밋은 `commit()`으로."""
    n = Notification(
        notification_id=new_id(),
        user_id=user_id,
        type=type_,
        title=title,
        body=body,
        target_url=target_url,
        is_read=False,
        created_at=now_kst(),
    )
    db.add(n)
    db.info.setdefault("notifications", []).append(n)
    return n


async def commit(db: AsyncSession) -> None:
    """커밋한 뒤에 SSE로 알림을 내보낸다."""
    pending = db.info.pop("notifications", [])
    await db.commit()
    for n in pending:
        hub.publish(n.user_id, to_item(n))


# ---- 조회 ----


def _encode_cursor(n: Notification) -> str:
    return base64.urlsafe_b64encode(f"{n.created_at.isoformat()}|{n.notification_id}".encode()).decode()


def _decode_cursor(cursor: str):
    from datetime import datetime

    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts, nid = raw.split("|", 1)
        return datetime.fromisoformat(ts), nid
    except Exception:
        raise validation_failed(field_error("cursor", "INVALID_CURSOR", "잘못된 커서입니다."))


async def list_notifications(
    db: AsyncSession, user_id: str, unread_only: bool, cursor: str | None, size: int
) -> dict:
    size = max(1, min(size, 50))
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    if cursor:
        ts, nid = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Notification.created_at < ts,
                and_(Notification.created_at == ts, Notification.notification_id < nid),
            )
        )
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.notification_id.desc()).limit(size + 1)
    rows = list((await db.scalars(stmt)).all())
    has_more = len(rows) > size
    rows = rows[:size]
    return {
        "items": [to_item(n) for n in rows],
        "nextCursor": _encode_cursor(rows[-1]) if has_more and rows else None,
    }


async def unread_count(db: AsyncSession, user_id: str) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
        )
    ) or 0


async def mark_read(db: AsyncSession, user_id: str, notification_id: str) -> None:
    n = await db.get(Notification, notification_id)
    if n is None or n.user_id != user_id:
        raise not_found()
    if not n.is_read:
        n.is_read = True
        await db.commit()


async def mark_all_read(db: AsyncSession, user_id: str) -> None:
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    await db.commit()


async def backlog_after(db: AsyncSession, user_id: str, last_event_id: str) -> list[Notification]:
    """Last-Event-ID 이후에 쌓인 알림 (SSE 재연결용)."""
    ref = await db.get(Notification, last_event_id)
    if ref is None or ref.user_id != user_id:
        return []
    stmt = (
        select(Notification)
        .where(
            Notification.user_id == user_id,
            or_(
                Notification.created_at > ref.created_at,
                and_(Notification.created_at == ref.created_at, Notification.notification_id > ref.notification_id),
            ),
        )
        .order_by(Notification.created_at, Notification.notification_id)
    )
    return list((await db.scalars(stmt)).all())


async def purge_old(db: AsyncSession) -> int:
    from datetime import timedelta

    cutoff = now_kst() - timedelta(days=settings.notification_retention_days)
    res = await db.execute(delete(Notification).where(Notification.created_at < cutoff))
    await db.commit()
    return res.rowcount or 0
