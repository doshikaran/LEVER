"""Run the Hero 1 real-code fidelity spike in one E2B base sandbox."""

import json
import math
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from e2b import Sandbox
from scipy.stats import qmc


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = PROJECT_ROOT / "fixtures" / "hero1"
SANDBOX_DIR = "/tmp/lever_fidelity"
LIMIT_PER_SECOND = 100
SOBOL_M = 6
POINT_COUNT = 2**SOBOL_M

DRIVER_TEMPLATE = """\
import importlib.util
import json
import time

LIMIT_PER_SECOND = __LIMIT_PER_SECOND__
POINTS = __POINTS__


def load_rate_limiter(path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import {module_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RateLimiter


BaseRateLimiter = load_rate_limiter("__SANDBOX_DIR__/base.py", "hero1_base")
HeadRateLimiter = load_rate_limiter("__SANDBOX_DIR__/head.py", "hero1_head")

for point in POINTS:
    rps = point["rps"]
    tenants = point["tenants"]
    base = BaseRateLimiter(LIMIT_PER_SECOND)
    head = HeadRateLimiter(LIMIT_PER_SECOND)
    admitted_base = 0
    admitted_head = 0
    started_at = time.time()

    # Every tenant sends one request at each of the rps evenly spaced times.
    for request_index in range(rps):
        now = started_at + request_index / rps
        for tenant_index in range(tenants):
            tenant_id = f"tenant-{tenant_index}"
            admitted_base += base.admit(tenant_id, now)
            admitted_head += head.admit(tenant_id, now)

    print(
        json.dumps(
            {
                "rps": rps,
                "tenants": tenants,
                "admitted_base": admitted_base,
                "admitted_head": admitted_head,
            }
        )
    )
"""


def sample_points() -> list[dict[str, int]]:
    """Generate 64 power-of-two Sobol points over log-scaled RPS and tenants."""
    sobol = qmc.Sobol(d=2, scramble=False)
    samples = sobol.random_base2(m=SOBOL_M)

    points = []
    for rps_sample, tenant_sample in samples:
        rps = round(10 ** (math.log10(1) + rps_sample * math.log10(1000)))
        tenants = min(16, math.floor(tenant_sample * 16) + 1)
        points.append({"rps": max(1, min(1000, rps)), "tenants": tenants})

    if len(points) != POINT_COUNT:
        raise RuntimeError(f"Expected {POINT_COUNT} Sobol points, got {len(points)}")
    return points


def build_driver(points: list[dict[str, int]]) -> str:
    """Embed generated points in the one-shot sandbox driver."""
    return (
        DRIVER_TEMPLATE.replace("__LIMIT_PER_SECOND__", str(LIMIT_PER_SECOND))
        .replace("__POINTS__", json.dumps(points))
        .replace("__SANDBOX_DIR__", SANDBOX_DIR)
    )


def main() -> None:
    """Upload Hero 1, execute all sampled traffic, and report real-code results."""
    load_dotenv(PROJECT_ROOT / ".env")
    if not os.environ.get("E2B_API_KEY"):
        raise RuntimeError("E2B_API_KEY must be set in .env")

    points = sample_points()
    driver = build_driver(points)
    started_at = time.perf_counter()
    sandbox = None

    try:
        # Calling create without a template selects E2B's base template.
        sandbox = Sandbox.create()
        sandbox.files.write(
            f"{SANDBOX_DIR}/base.py",
            (FIXTURE_DIR / "base.py").read_text(encoding="utf-8"),
        )
        sandbox.files.write(
            f"{SANDBOX_DIR}/head.py",
            (FIXTURE_DIR / "head.py").read_text(encoding="utf-8"),
        )
        sandbox.files.write(f"{SANDBOX_DIR}/driver.py", driver)

        # All 64 points run in one sandbox command, avoiding per-point startup.
        result = sandbox.commands.run(
            f"python3 {SANDBOX_DIR}/driver.py",
            timeout=120,
        )
        if result.exit_code != 0:
            raise RuntimeError(
                f"Sandbox driver failed (exit {result.exit_code}): {result.stderr}"
            )
        reports = [json.loads(line) for line in result.stdout.splitlines() if line]
        if len(reports) != POINT_COUNT:
            raise RuntimeError(
                f"Expected {POINT_COUNT} point reports, got {len(reports)}"
            )
    finally:
        if sandbox is not None:
            sandbox.kill()

    elapsed_seconds = time.perf_counter() - started_at
    for report in reports:
        print(
            "rps={rps}, tenants={tenants}, admitted_base={admitted_base}, "
            "admitted_head={admitted_head}".format(**report)
        )

    visible_points = [
        report
        for report in reports
        if report["admitted_head"] > report["admitted_base"]
    ]
    largest_gap = max(
        reports,
        key=lambda report: report["admitted_head"] - report["admitted_base"],
    )
    gap = largest_gap["admitted_head"] - largest_gap["admitted_base"]

    print(f"Visible bug points: {len(visible_points)} of {POINT_COUNT}")
    print(
        "Largest gap: "
        "rps={rps}, tenants={tenants}, admitted_base={admitted_base}, "
        "admitted_head={admitted_head}, gap={gap}".format(
            **largest_gap,
            gap=gap,
        )
    )
    print(f"Total wall-clock time: {elapsed_seconds:.2f}s")


if __name__ == "__main__":
    main()
