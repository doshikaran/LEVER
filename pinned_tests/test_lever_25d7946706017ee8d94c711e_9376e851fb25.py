"""Pinned by Lever from change '25d7946706017ee8d94c711ed004d313c8140b300113f76d6abffbb15e3098b5'."""

import json
from pathlib import Path

import pytest

from domain.harness_engineer import HarnessEngineer
from domain.schema import PartialInteractionSpec
from domain.scout import scout
from infra.parsing.tree_sitter_adapter import TreeSitterPythonParser

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_FILE = REPO_ROOT / 'fixtures/hero3/base.py'
HEAD_FILE = REPO_ROOT / 'fixtures/hero3/head.py'
POSITION = json.loads('{"resource": "audit-log", "role": "contractor", "same_tenant": false}')
EXPECTED_HEAD = json.loads('{"allowed": true}')
TOLERANCE = json.loads('{"kind": "exact"}')
PARTIAL_SPEC = PartialInteractionSpec.model_validate(json.loads('{"domainPack": "permission", "knobs": [{"axisRole": "x", "binding": {"argIndex": 0, "fn": "can", "kind": "argument"}, "default": "contractor", "domain": {"values": ["viewer", "editor", "admin", "contractor"]}, "id": "role", "label": "Role", "scale": "linear", "type": "enum", "unit": null}, {"axisRole": "y", "binding": {"argIndex": 2, "fn": "can", "kind": "argument"}, "default": "audit-log", "domain": {"values": ["doc", "billing", "audit-log", "settings"]}, "id": "resource", "label": "Resource", "scale": "linear", "type": "enum", "unit": null}, {"axisRole": null, "binding": {"argIndex": 3, "fn": "can", "kind": "argument"}, "default": false, "domain": {"values": ["false", "true"]}, "id": "same_tenant", "label": "Same tenant", "scale": "linear", "type": "boolean", "unit": null}], "observables": [{"compareMode": "overlay", "extractor": {"kind": "returnValue", "path": "$"}, "id": "allowed", "label": "Permission granted", "render": "matrixCell", "unit": null}], "thesis": "Cross-tenant reads now honor transitive group grants, letting contractors read audit-log; direct and same-tenant results stay unchanged."}'))


# Lever trace attribution: fixtures/hero3/head.py:28 — if resource in ROLE_PERMISSIONS.get(role, set()):
def test_lever_25d7946706017ee8d94c711e_9376e851fb25() -> None:
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
