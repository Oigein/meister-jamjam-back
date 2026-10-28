"""세션·임시 값 저장소. 기본은 인메모리. Redis로 바꾸려면 같은 인터페이스로 구현해 `set_kv`로 교체한다."""
import time
from typing import Any, Protocol


class KV(Protocol):
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl: int) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def touch(self, key: str, ttl: int) -> None: ...


class MemoryKV:
    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float]] = {}

    async def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, expires = item
        if expires < time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: Any, ttl: int) -> None:
        self._data[key] = (value, time.monotonic() + ttl)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def touch(self, key: str, ttl: int) -> None:
        item = self._data.get(key)
        if item is not None:
            self._data[key] = (item[0], time.monotonic() + ttl)

    def clear(self) -> None:
        self._data.clear()


_kv: KV = MemoryKV()


def get_kv() -> KV:
    return _kv


def set_kv(kv: KV) -> None:
    global _kv
    _kv = kv
