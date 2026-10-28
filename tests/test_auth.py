from urllib.parse import parse_qs, urlparse

import pytest

from app.common.enums import Role
from app.core.config import settings
from app.domains.auth.oauth import GoogleError, GoogleUnavailable, get_google_client
from app.domains.auth.service import safe_redirect
from app.domains.user.models import User


class FakeGoogle:
    def __init__(self, claims=None, error=None):
        self.claims = claims
        self.error = error
        self.last_challenge = None

    def authorization_url(self, state, nonce, code_challenge):
        self.last_challenge = code_challenge
        return f"https://accounts.google.com/auth?state={state}&nonce={nonce}"

    async def fetch_claims(self, code, code_verifier, nonce):
        if self.error:
            raise self.error
        return self.claims


def claims(email="s1@bssm.hs.kr", **over):
    base = {"sub": "google-sub-1", "email": email, "email_verified": True, "hd": "bssm.hs.kr",
            "name": "홍길동", "picture": "https://lh3.googleusercontent.com/a/x"}
    base.update(over)
    return base


async def start(client, fake, redirect=None):
    from app.domains.auth.oauth import get_google_client as dep

    client._transport.app.dependency_overrides[dep] = lambda: fake
    r = await client.get("/auth/google", params={"redirect": redirect} if redirect else None,
                         follow_redirects=False)
    assert r.status_code == 302
    return parse_qs(urlparse(r.headers["location"]).query)["state"][0]


async def callback(client, state, **params):
    return await client.get("/auth/google/callback", params={"code": "c", "state": state, **params},
                            follow_redirects=False)


@pytest.fixture
async def roster(db):
    u = User(name="명단이름", email="s1@bssm.hs.kr", role=Role.STUDENT)  # google_id 없음(사전 등록)
    db.add(u)
    await db.commit()
    return u


async def test_login_success_links_google_id_and_sets_cookie(anon, db, roster):
    fake = FakeGoogle(claims())
    state = await start(anon, fake, redirect="/students/abc")
    assert fake.last_challenge  # PKCE
    r = await callback(anon, state)
    assert r.status_code == 302 and r.headers["location"] == "/students/abc"
    cookie = r.headers["set-cookie"]
    assert "SESSION=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Max-Age=604800" in cookie
    await db.refresh(roster)
    assert roster.google_id == "google-sub-1" and roster.name == "홍길동"
    assert roster.profile_image_url.startswith("https://lh3")


async def test_default_redirect_is_ranking(anon, roster):
    state = await start(anon, FakeGoogle(claims()))
    assert (await callback(anon, state)).headers["location"] == "/ranking"


async def test_me_after_login(make_client, anon, roster, db):
    state = await start(anon, FakeGoogle(claims()))
    r = await callback(anon, state)
    sid = r.headers["set-cookie"].split("SESSION=")[1].split(";")[0]
    c = await make_client()
    me = await c.get("/api/me", headers={"Cookie": f"SESSION={sid}"})
    assert me.status_code == 200 and me.json()["role"] == "STUDENT"
    assert me.json()["student"] is None  # 학생 행이 없는 명단


@pytest.mark.parametrize(
    "fake,error",
    [
        (FakeGoogle(claims("a@gmail.com", hd="gmail.com")), "DOMAIN_NOT_ALLOWED"),
        (FakeGoogle(claims(hd=None)), "DOMAIN_NOT_ALLOWED"),
        (FakeGoogle(claims(email_verified=False)), "DOMAIN_NOT_ALLOWED"),
        (FakeGoogle(claims("x@evil.com")), "DOMAIN_NOT_ALLOWED"),
        (FakeGoogle(claims("who@bssm.hs.kr", sub="other")), "NOT_REGISTERED"),
        (FakeGoogle(error=GoogleError()), "AUTH_FAILED"),
        (FakeGoogle(error=GoogleUnavailable()), "GOOGLE_UNAVAILABLE"),
    ],
)
async def test_login_failures_redirect_with_error(anon, roster, fake, error):
    state = await start(anon, fake)
    r = await callback(anon, state)
    assert r.status_code == 302 and r.headers["location"] == f"/login?error={error}"
    assert "set-cookie" not in r.headers


async def test_state_mismatch_and_reuse(anon, roster):
    fake = FakeGoogle(claims())
    state = await start(anon, fake)
    assert (await callback(anon, "wrong")).headers["location"] == "/login?error=AUTH_FAILED"
    assert (await callback(anon, state)).status_code == 302
    # state는 한 번만 쓸 수 있다
    assert (await callback(anon, state)).headers["location"] == "/login?error=AUTH_FAILED"


async def test_user_cancel_redirects_without_error(anon, roster):
    state = await start(anon, FakeGoogle(claims()))
    r = await anon.get("/auth/google/callback", params={"error": "access_denied", "state": state},
                       follow_redirects=False)
    assert r.headers["location"] == "/login"


async def test_google_id_conflict_is_auth_failed(anon, roster, db):
    roster.google_id = "someone-else"
    await db.commit()
    state = await start(anon, FakeGoogle(claims()))
    assert (await callback(anon, state)).headers["location"] == "/login?error=AUTH_FAILED"


@pytest.mark.parametrize(
    "value,expected",
    [("/students/1", "/students/1"), ("//evil.com", None), ("https://evil.com", None),
     ("/\\evil.com", None), ("students", None), (None, None), ("/ranking?grade=2", "/ranking?grade=2")],
)
def test_safe_redirect(value, expected):
    assert safe_redirect(value) == expected


async def test_login_rate_limit(anon):
    anon._transport.app.dependency_overrides[get_google_client] = lambda: FakeGoogle(claims())
    for _ in range(settings.rate_login_per_min):
        assert (await anon.get("/auth/google", follow_redirects=False)).status_code == 302
    r = await anon.get("/auth/google", follow_redirects=False)
    assert r.status_code == 429 and r.headers["retry-after"] and r.json()["code"] == "TOO_MANY_REQUESTS"


async def test_logout_clears_session(make_client, db):
    from tests.factories import make_student

    user = await make_student(db)
    c = await make_client(user)
    assert (await c.get("/api/me")).status_code == 200
    r = await c.post("/auth/logout")
    assert r.status_code == 204 and "Max-Age=0" in r.headers["set-cookie"]
    assert (await c.get("/api/me")).status_code == 401
    # 세션이 없어도 같은 응답
    assert (await (await make_client()).post("/auth/logout")).status_code == 204


async def test_relogin_updates_changed_email(anon, db, roster):
    roster.google_id = "google-sub-1"
    await db.commit()
    state = await start(anon, FakeGoogle(claims("renamed@bssm.hs.kr")))
    assert (await callback(anon, state)).headers["location"] == "/ranking"
    await db.refresh(roster)
    assert roster.email == "renamed@bssm.hs.kr"  # sub가 기준 키, 이메일은 보조 값


async def test_relogin_rejects_email_owned_by_someone_else(anon, db, roster):
    roster.google_id = "google-sub-1"
    db.add(User(name="다른 사람", email="taken@bssm.hs.kr", role=Role.STUDENT))
    await db.commit()
    state = await start(anon, FakeGoogle(claims("taken@bssm.hs.kr")))
    assert (await callback(anon, state)).headers["location"] == "/login?error=AUTH_FAILED"
    await db.refresh(roster)
    assert roster.email == "s1@bssm.hs.kr"
