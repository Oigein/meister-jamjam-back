import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

import app.models  # noqa: F401  (모델 등록)
from app.api import api_router, auth_router
from app.common.exceptions import register_exception_handlers
from app.common.storage import public_storage
from app.core.config import settings
from app.core.database import Base, get_engine, get_sessionmaker
from app.core.security import check_origin
from app.core.seed import seed_defaults

logger = logging.getLogger("app")


async def _periodic_cleanup() -> None:
    from app.domains.notification.service import purge_old
    from app.domains.report.service import cleanup_orphan_attachments

    while True:
        try:
            async with get_sessionmaker()() as db:
                await cleanup_orphan_attachments(db)
                await purge_old(db)
        except Exception:  # 정리 작업 실패가 서버를 멈추면 안 된다
            logger.exception("cleanup failed")
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_tables:
        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    if settings.seed_on_startup:
        async with get_sessionmaker()() as db:
            await seed_defaults(db)
    task = asyncio.create_task(_periodic_cleanup()) if settings.run_background_jobs else None
    yield
    if task:
        task.cancel()


app = FastAPI(title=settings.app_name, lifespan=lifespan, dependencies=[Depends(check_origin)])
register_exception_handlers(app)
app.include_router(auth_router)
app.include_router(api_router)
app.mount("/media", StaticFiles(directory=public_storage().root), name="media")


@app.get("/")
def root():
    return {"message": "meister-jamjam-back is running"}


@app.get("/health")
def health():
    return {"status": "ok"}
