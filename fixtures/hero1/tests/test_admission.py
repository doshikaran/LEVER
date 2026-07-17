"""Executable reference — satisfies the Verifier's precondition."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def test_base_admits_up_to_limit():
    from base import RateLimiter
    rl = RateLimiter(limit_per_sec=5)
    assert sum(rl.admit("t1", 0.0 + i * 0.01) for i in range(10)) == 5

def test_head_admits_up_to_limit_plus_burst():
    from head import RateLimiter
    rl = RateLimiter(limit_per_sec=5, burst=2)
    assert sum(rl.admit("t1", 0.0 + i * 0.01) for i in range(10)) == 7