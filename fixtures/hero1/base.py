"""Fixed-window rate limiter — the 'old' version."""
import time

class RateLimiter:
    def __init__(self, limit_per_sec: int):
        self.limit = limit_per_sec
        self.window_start = time.time()
        self.count = 0

    def admit(self, tenant_id: str, now: float) -> bool:
        if now - self.window_start >= 1.0:
            self.window_start = now
            self.count = 0
        if self.count < self.limit:
            self.count += 1
            return True
        return False