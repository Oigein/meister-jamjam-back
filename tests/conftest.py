import os
import tempfile

# app을 import하기 전에 테스트용 환경으로 맞춘다
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="jamjam-test-")
os.environ["AUTO_CREATE_TABLES"] = "false"
os.environ["SEED_ON_STARTUP"] = "false"
os.environ["RUN_BACKGROUND_JOBS"] = "false"
os.environ["COOKIE_SECURE"] = "false"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.common.kv import MemoryKV, get_kv
from app.common.ratelimit import limiter
from app.core.config import settings
from app.core.database import Base, get_sessionmaker, init_engine
from app.core.security import create_session
from app.core.seed import seed_defaults
from app.main import app

ORIGIN = "http://localhost:3000"


@pytest_asyncio.fixture
async def engine():
    eng = init_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with get_sessionmaker()() as s:
        await seed_defaults(s)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    async with get_sessionmaker()() as session:
        yield session


@pytest.fixture(autouse=True)
def _reset_state():
    kv = get_kv()
    if isinstance(kv, MemoryKV):
        kv.clear()
    limiter.clear()
    settings.service_origins = [ORIGIN]
    settings.enforce_origin = True
    yield
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def make_client(engine):
    clients: list[AsyncClient] = []

    async def _make(user=None, origin: str | None = ORIGIN) -> AsyncClient:
        headers = {"Origin": origin} if origin else {}
        if user is not None:
            headers["Cookie"] = f"{settings.cookie_name}={await create_session(user.user_id)}"
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers)
        clients.append(c)
        return c

    yield _make
    for c in clients:
        await c.aclose()


@pytest_asyncio.fixture
async def anon(make_client):
    return await make_client()
