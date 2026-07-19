"""Pinned by Lever from change 'hero1-measured-e2b'."""

import json
from pathlib import Path

import pytest

from domain.harness_engineer import HarnessEngineer
from domain.schema import PartialInteractionSpec
from domain.scout import scout
from infra.parsing.tree_sitter_adapter import TreeSitterPythonParser

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_FILE = REPO_ROOT / 'fixtures/hero1/base.py'
HEAD_FILE = REPO_ROOT / 'fixtures/hero1/head.py'
POSITION = json.loads('{"burst": 10.0, "limit_per_sec": 50.0, "rps": 81.0, "tenants": 20.0}')
EXPECTED_HEAD = json.loads('{"admitted": 1010}')
TOLERANCE = json.loads('{"epsilon": 0.01, "kind": "relative"}')
PARTIAL_SPEC = PartialInteractionSpec.model_validate(json.loads('{"domainPack": "rate-limiter", "knobs": [{"axisRole": null, "binding": {"kind": "config", "path": "limit_per_sec"}, "default": 5.0, "domain": {"max": 100.0, "min": 1.0, "step": 1.0}, "id": "limit_per_sec", "label": "limit", "scale": "linear", "type": "integer", "unit": "requests/s"}, {"axisRole": null, "binding": {"kind": "config", "path": "burst"}, "default": 2.0, "domain": {"max": 50.0, "min": 0.0, "step": 1.0}, "id": "burst", "label": "burst", "scale": "linear", "type": "integer", "unit": "requests"}, {"axisRole": null, "binding": {"kind": "driver", "param": "rps"}, "default": 3.0, "domain": {"max": 100.0, "min": 1.0, "step": 1.0}, "id": "rps", "label": "rps", "scale": "linear", "type": "integer", "unit": "requests/s"}, {"axisRole": null, "binding": {"kind": "driver", "param": "tenants"}, "default": 2.0, "domain": {"max": 16.0, "min": 1.0, "step": 1.0}, "id": "tenants", "label": "tenants", "scale": "linear", "type": "integer", "unit": "tenants"}], "observables": [{"compareMode": "overlay", "extractor": {"kind": "counter", "name": "admitted"}, "id": "admitted", "label": "admitted", "render": "timeseries", "unit": "requests"}], "thesis": "Head adds a shared burst allowance to the per-tenant limiter."}'))


# Lever trace attribution: fixtures/hero1/head.py:19 — if len(w) < self.limit:
def test_lever_hero1_measured_e2b_fa6232375bf0() -> None:
    base_source = BASE_FILE.read_text()
    head_source = HEAD_FILE.read_text()
    parser = TreeSitterPythonParser()
    scope = scout(
        base_source,
        head_source,
        parser.parse(base_source, "python"),
        parser.parse(head_source, "python"),
        str(BASE_FILE),
        str(HEAD_FILE),
    )
    assert scope.entry_point is not None, scope.reason

    # Regenerate production's head harness; do not duplicate its workload driver here.
    pair = HarnessEngineer().generate(scope, PARTIAL_SPEC, str(BASE_FILE), str(HEAD_FILE))
    namespace: dict[str, object] = {"__name__": "lever_pinned_harness"}
    exec(compile(pair.harness_b.source, "<lever pinned head harness>", "exec"), namespace)
    observed = namespace["run"](POSITION, 0)["observations"]  # type: ignore[operator]

    for observable_id, expected in EXPECTED_HEAD.items():
        assert observable_id in observed
        actual = observed[observable_id]
        if (
            TOLERANCE["kind"] == "relative"
            and isinstance(expected, (int, float))
            and not isinstance(expected, bool)
        ):
            assert actual == pytest.approx(expected, rel=TOLERANCE["epsilon"])
        elif TOLERANCE["kind"] == "absolute" and isinstance(expected, (int, float)):
            assert actual == pytest.approx(expected, abs=TOLERANCE["epsilon"])
        else:
            assert actual == expected
