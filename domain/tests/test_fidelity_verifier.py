"""Fake-runtime confidence coverage for Symmetrist-first fidelity verification."""

import json
import math

from domain.fidelity_verifier import FidelityVerifier, SOBOL_POINT_COUNT
from domain.harness_engineer import HarnessEngineer
from infra.fakes.fake_sandbox import FakeSandboxRuntime

from test_harness_engineer import _hero_scope, _hero_spec


def test_fidelity_confidence_uses_agreement_stability_and_coverage_with_fake_runtime() -> None:
    """Half of the Sobol points agreeing produces the exact low-band product with no stubs."""
    scripted_results = []
    for point_index in range(SOBOL_POINT_COUNT):
        matching = point_index >= SOBOL_POINT_COUNT // 2
        base_reference = {"admitted": 1 if matching else 2}
        for observations in (
            {"admitted": 1},
            base_reference,
            {"admitted": 1},
            {"admitted": 1},
        ):
            scripted_results.append(
                {"stdout": json.dumps(observations), "stderr": "", "exit_code": 0}
            )
    for _ in range(SOBOL_POINT_COUNT // 2 * 12 * 2):
        scripted_results.append(
            {"stdout": json.dumps({"admitted": 1}), "stderr": "", "exit_code": 0}
        )
    runtime = FakeSandboxRuntime(scripted_results=scripted_results)
    sandbox_id = runtime.create_sandbox("base")

    def scripted_runner(kind: str, point: dict, seed: int) -> dict:
        result = runtime.run_code(sandbox_id, "print('scripted')")
        return json.loads(result["stdout"])

    pair = HarnessEngineer().generate(
        _hero_scope(), _hero_spec(), "/tmp/base.py", "/tmp/head.py"
    )
    verification = FidelityVerifier(runtime, scripted_runner).verify(
        sandbox_id,
        pair,
        _hero_scope(),
        _hero_spec(),
        "base source is unused by the injected fake runner",
        "head source is unused by the injected fake runner",
    )

    expected_coverage = math.log1p(SOBOL_POINT_COUNT) / math.log1p(256)
    assert verification.report.agreement.samples == SOBOL_POINT_COUNT
    assert verification.report.agreement.matched == SOBOL_POINT_COUNT // 2
    assert verification.report.agreement.rate == 0.5
    assert verification.report.stability.perObservable["admitted"].value == 0.0
    # Hero 1 has no uncertainty dimensions: the Assayer therefore contributes 1.
    assert verification.report.confidence == 0.5 * expected_coverage
    assert verification.report.band == "low"
    assert len(verification.mismatches) == SOBOL_POINT_COUNT // 2
    runtime.kill_sandbox(sandbox_id)
