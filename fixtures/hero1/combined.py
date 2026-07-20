"""Hero 1 composition AB: both tenant isolation and the raised limit apply."""

from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit_per_sec: int, burst: int = 0):
        self.limit = limit_per_sec * 2
        self.burst = burst
        self.windows = defaultdict(deque)
        self.burst_used = 0  # Intentionally shared, as in diff A.

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
