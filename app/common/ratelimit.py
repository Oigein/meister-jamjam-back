import time
from collections import defaultdict, deque

from fastapi import Request

from app.common.exceptions import AppException


class MemoryRateLimiter:
    """슬라이딩 윈도우. 프로세스 단위라서 여러 서버를 쓰면 Redis 구현으로 교체한다."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str, limit: int, window: float) -> int | None:
        """허용이면 None, 초과면 Retry-After(초)를 돌려준다."""
        now = time.monotonic()
        q = self._hits[key]
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= limit:
            return max(1, int(q[0] + window - now) + 1)
        q.append(now)
        return None

    def clear(self) -> None:
        self._hits.clear()


limiter = MemoryRateLimiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def too_many(retry_after: int) -> AppException:
    return AppException(
        429,
        "TOO_MANY_REQUESTS",
        "요청이 너무 많습니다. 잠시 후 다시 시도하세요.",
        headers={"Retry-After": str(retry_after)},
    )


def check_ip_limit(request: Request, name: str, limit: int, window: float = 60) -> None:
    retry = limiter.hit(f"{name}:ip:{client_ip(request)}", limit, window)
    if retry is not None:
        raise too_many(retry)


def check_user_limit(user_id: str, name: str, limit: int, window: float = 60) -> None:
    retry = limiter.hit(f"{name}:user:{user_id}", limit, window)
    if retry is not None:
        raise too_many(retry)
