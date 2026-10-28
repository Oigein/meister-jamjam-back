from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import Enum, event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def enum_col(enum_cls: type, length: int = 30) -> Enum:
    """ENUM은 VARCHAR로 저장해 MySQL·SQLite에서 같게 동작시킨다."""
    return Enum(enum_cls, native_enum=False, length=length, validate_strings=True)


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(url: str | None = None, **kwargs: Any) -> AsyncEngine:
    global _engine, _sessionmaker
    url = url or settings.database_url
    _engine = create_async_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(_engine.sync_engine, "connect")
        def _fk_on(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        init_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session
