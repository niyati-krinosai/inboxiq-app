import asyncio
import time
from collections import deque


class GmailRateLimiter:
    """Token-bucket rate limiter for Gmail API quota (250 units/user/sec, we stay conservative)."""

    def __init__(self, max_requests: int = 40, window_seconds: float = 1.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            while self._timestamps and now - self._timestamps[0] > self.window_seconds:
                self._timestamps.popleft()
            if len(self._timestamps) >= self.max_requests:
                sleep_for = self.window_seconds - (now - self._timestamps[0])
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
            self._timestamps.append(time.monotonic())


gmail_limiter = GmailRateLimiter()
