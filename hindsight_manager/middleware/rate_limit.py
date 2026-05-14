import time
from collections import defaultdict

from fastapi import HTTPException, Request, status


class RateLimiter:
    """In-memory sliding window rate limiter used as a FastAPI dependency."""

    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def __call__(self, request: Request) -> None:
        key = f"{request.client.host}:{request.url.path}"
        now = time.time()
        cutoff = now - self.window_seconds

        timestamps = self._requests[key]
        self._requests[key] = [t for t in timestamps if t > cutoff]

        if len(self._requests[key]) >= self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests",
                headers={"Retry-After": str(self.window_seconds)},
            )

        self._requests[key].append(now)


login_limiter = RateLimiter(max_requests=5, window_seconds=60)
otp_limiter = RateLimiter(max_requests=10, window_seconds=60)
password_limiter = RateLimiter(max_requests=3, window_seconds=60)
