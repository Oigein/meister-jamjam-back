import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import quote

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.kv import get_kv
from app.core.config import settings
from app.core.security import create_session
from app.domains.auth.oauth import GoogleClient, GoogleError, GoogleUnavailable
from app.domains.user import repository as users

STATE_TTL = 600


def safe_redirect(value: str | None) -> str | None:
    """서비스 내부 경로(`/`로 시작)만 허용한다. `//evil.com`, `/\\evil.com`, 외부 URL은 무시."""
    if not value or not value.startswith("/"):
        return None
    if value.startswith("//") or value.startswith("/\\") or "\\" in value:
        return None
    if any(ord(c) < 32 for c in value):
        return None
    return value


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


async def start_login(client: GoogleClient, redirect: str | None) -> str:
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    await get_kv().set(
        f"oauth:{state}",
        {"verifier": verifier, "nonce": nonce, "redirect": safe_redirect(redirect)},
        STATE_TTL,
    )
    return client.authorization_url(state, nonce, _challenge(verifier))


@dataclass
class CallbackResult:
    location: str
    session_id: str | None = None


def _fail(error: str | None) -> CallbackResult:
    return CallbackResult("/login" if error is None else f"/login?error={quote(error)}")


async def finish_login(
    db: AsyncSession,
    client: GoogleClient,
    code: str | None,
    state: str | None,
    error: str | None,
) -> CallbackResult:
    kv = get_kv()
    saved = await kv.get(f"oauth:{state}") if state else None
    if state:
        await kv.delete(f"oauth:{state}")  # state는 한 번만 쓴다

    if error:  # 사용자가 구글 동의를 취소한 경우: 오류 코드·문구 없이 로그인 화면으로
        return _fail(None)
    if saved is None or not code:
        return _fail("AUTH_FAILED")

    try:
        claims = await client.fetch_claims(code, saved["verifier"], saved["nonce"])
    except GoogleUnavailable:
        return _fail("GOOGLE_UNAVAILABLE")
    except GoogleError:
        return _fail("AUTH_FAILED")

    # 요청의 hd는 힌트일 뿐이므로 토큰에서 다시 검사한다
    email = str(claims.get("email", "")).lower()
    domain = settings.allowed_email_domain
    if (
        claims.get("email_verified") is not True
        or claims.get("hd") != domain
        or not email.endswith(f"@{domain}")
    ):
        return _fail("DOMAIN_NOT_ALLOWED")
    sub = claims.get("sub")
    if not sub:
        return _fail("AUTH_FAILED")

    user = await users.get_user_by_google_id(db, sub)
    if user is not None and user.email != email:
        # sub가 기준 키라 이메일이 바뀌어도 같은 사용자다. 다른 사용자가 쓰는 이메일이면 거부한다
        other = await users.get_user_by_email(db, email)
        if other is not None and other.user_id != user.user_id:
            return _fail("AUTH_FAILED")
        user.email = email
    if user is None:
        user = await users.get_user_by_email(db, email)
        if user is None:
            return _fail("NOT_REGISTERED")
        if user.google_id and user.google_id != sub:
            return _fail("AUTH_FAILED")
        user.google_id = sub
    if claims.get("name"):
        user.name = claims["name"]
    if claims.get("picture"):
        user.profile_image_url = claims["picture"]
    await db.commit()

    sid = await create_session(user.user_id)
    return CallbackResult(saved.get("redirect") or settings.login_default_redirect, sid)
