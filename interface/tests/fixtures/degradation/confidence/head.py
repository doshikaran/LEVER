class RateLimiter:
    def __init__(self, limit_per_sec: int = 10, burst: int = 0) -> None:
        self.limit_per_sec = limit_per_sec

    def admit(self, tenant_id: str, now: float) -> int:
        return 2
