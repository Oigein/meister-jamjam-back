import secrets

from fastapi import Request, Response

from app.common.exceptions import forbidden
from app.common.kv import get_kv
from app.core.config import settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


async def create_session(user_id: str) -> str:
    sid = secrets.token_urlsafe(32)
    await get_kv().set(f"session:{sid}", user_id, settings.session_ttl_seconds)
    return sid


async def resolve_session(sid: str | None) -> str | None:
    """세션 주인의 user_id를 돌려주고, 사용할 때마다 유효기간을 갱신한다."""
    if not sid:
        return None
    kv = get_kv()
    user_id = await kv.get(f"session:{sid}")
    if user_id is not None:
        await kv.touch(f"session:{sid}", settings.session_ttl_seconds)
    return user_id


async def destroy_session(sid: str | None) -> None:
    if sid:
        await get_kv().delete(f"session:{sid}")


def set_session_cookie(response: Response, sid: str) -> None:
    response.set_cookie(
        settings.cookie_name,
        sid,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.set_cookie(
        settings.cookie_name,
        "",
        max_age=0,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


async def check_origin(request: Request) -> None:
    """변경 요청(POST·PUT·PATCH·DELETE)은 Origin이 서비스 도메인일 때만 처리한다."""
    if not settings.enforce_origin or request.method in SAFE_METHODS:
        return
    if request.headers.get("origin") not in settings.service_origins:
        raise forbidden("허용되지 않은 요청 출처입니다.")
