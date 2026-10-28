"""파일 저장소. 기본은 로컬 디스크. S3 등으로 바꾸려면 같은 메서드를 구현해 교체한다."""
import asyncio
import uuid
from pathlib import Path

from app.core.config import settings


class LocalStorage:
    def __init__(self, root: Path, url_prefix: str | None = None) -> None:
        self.root = root
        self.url_prefix = url_prefix
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("잘못된 파일 경로")
        return path

    async def save(self, data: bytes, namespace: str, ext: str = "") -> str:
        key = f"{namespace}/{uuid.uuid4().hex}" + (f".{ext}" if ext else "")
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(_write)
        return key

    async def read(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str | None) -> None:
        if not key:
            return

        def _rm() -> None:
            self._path(key).unlink(missing_ok=True)

        await asyncio.to_thread(_rm)

    def url(self, key: str | None) -> str | None:
        if not key or self.url_prefix is None:
            return None
        return f"{self.url_prefix}/{key}"


def private_storage() -> LocalStorage:
    return LocalStorage(Path(settings.storage_dir) / "private")


def public_storage() -> LocalStorage:
    return LocalStorage(Path(settings.storage_dir) / "public", url_prefix="/media")
