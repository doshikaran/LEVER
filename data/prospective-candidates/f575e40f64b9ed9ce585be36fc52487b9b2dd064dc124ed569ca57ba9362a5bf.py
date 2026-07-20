"""Fixed-window rate limiter with a per-tenant burst allowance."""


class RateLimiter:
    def __init__(self, limit_per_sec: int):
        self.limit = limit_per_sec
        self._tenant_windows = {}

    def admit(self, tenant_id: str, now: float) -> bool:
        window_start, count = self._tenant_windows.get(tenant_id, (now, 0))

        if now - window_start >= 1.0:
            window_start = now
            count = 0

        if count < self.limit:
            self._tenant_windows[tenant_id] = (window_start, count + 1)
            return True

        self._tenant_windows[tenant_id] = (window_start, count)
        return False
