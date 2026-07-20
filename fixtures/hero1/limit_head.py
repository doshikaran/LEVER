"""Hero 1 composition diff B: raise the configured fixed-window limit.

This is deliberately a small, independent change on the same rate-limiter
subsystem as ``head.py``.  It doubles the supplied limit before admitting
requests; it does not contain the per-tenant window change from diff A.
"""

import time


class RateLimiter:
    def __init__(self, limit_per_sec: int):
        self.limit = limit_per_sec * 2
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
