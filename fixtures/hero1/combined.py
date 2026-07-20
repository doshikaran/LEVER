"""Sliding-window rate limiter with per-tenant burst — the 'new' version.
KNOWN BUG, intentional: burst allowance is shared across tenants instead
of being decremented per-tenant. This is Hero 1's surprise marker.
"""
import time
from collections import deque, defaultdict

class RateLimiter:
    def __init__(self, limit_per_sec: int, burst: int = 0):
        self.limit = limit_per_sec * 2
        self.burst = burst
        self.windows = defaultdict(deque)
        self.burst_used = 0  # BUG: shared, should be per-tenant

    def admit(self, tenant_id: str, now: float) -> bool:
        w = self.windows[tenant_id]
        while w and now - w[0] >= 1.0:
            w.popleft()
        if len(w) < self.limit:
            w.append(now)
            return True
        if self.burst_used < self.burst:
            self.burst_used += 1
            w.append(now)
            return True
        return False
