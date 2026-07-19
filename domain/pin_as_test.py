"""Pin a measured head behavior as a durable pytest regression test."""

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from domain.schema import InteractionSpec, KnobPosition, ResponsibleLine


def write_pinned_head_test(
    output_dir: str | Path,
    base_file_path: str | Path,
    head_file_path: str | Path,
    spec: InteractionSpec,
    position: KnobPosition,
    head_observations: Mapping[str, Any],
    responsible_line: ResponsibleLine | None = None,
) -> Path:
    """Write an idempotent regression test that regenerates the real head harness.

    The observed head values are the assertion oracle captured at pin time.  The
    emitted pytest test deliberately calls ``HarnessEngineer().generate`` at
    test time, so it shares the production driver and harness machinery rather
    than carrying a second, hand-written workload implementation.
    """
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    base_path = Path(base_file_path).resolve()
    head_path = Path(head_file_path).resolve()
    pinned_source = _render_pinned_test(
        target_dir.parent.resolve(),
        base_path,
        head_path,
        spec,
        position,
        dict(head_observations),
        responsible_line,
    )
    stem = _test_stem(spec.changeId, position)
    candidate = target_dir / f"{stem}.py"
    duplicate = 2
    while candidate.exists() and candidate.read_text() != pinned_source:
        candidate = target_dir / f"{stem}_{duplicate}.py"
        duplicate += 1
    if not candidate.exists():
        candidate.write_text(pinned_source)
    return candidate


def _render_pinned_test(
    repo_root: Path,
    base_path: Path,
    head_path: Path,
    spec: InteractionSpec,
    position: KnobPosition,
    head_observations: dict[str, Any],
    responsible_line: ResponsibleLine | None,
) -> str:
    """Render a self-contained pytest module whose driver comes from Harness Engineer."""
    partial_spec = {
        "thesis": spec.thesis,
        "domainPack": spec.domainPack,
        "knobs": [knob.model_dump(mode="json") for knob in spec.knobs],
        "observables": [observable.model_dump(mode="json") for observable in spec.observables],
    }
    tolerance = spec.fidelity.agreement.tolerance.model_dump(mode="json")
    comment = _responsible_comment(responsible_line, repo_root, head_path)
    position_json = json.dumps(position.root, sort_keys=True)
    expected_json = json.dumps(head_observations, sort_keys=True)
    partial_spec_json = json.dumps(partial_spec, sort_keys=True)
    tolerance_json = json.dumps(tolerance, sort_keys=True)
    test_name = _test_stem(spec.changeId, position).removeprefix("test_")
    base_reference = _source_reference(base_path, repo_root)
    head_reference = _source_reference(head_path, repo_root)
    return f'''\
"""Pinned by Lever from change {spec.changeId!r}."""

import json
from pathlib import Path

import pytest

from domain.harness_engineer import HarnessEngineer
from domain.schema import PartialInteractionSpec
from domain.scout import scout
from infra.parsing.tree_sitter_adapter import TreeSitterPythonParser

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_FILE = {base_reference}
HEAD_FILE = {head_reference}
POSITION = json.loads({position_json!r})
EXPECTED_HEAD = json.loads({expected_json!r})
TOLERANCE = json.loads({tolerance_json!r})
PARTIAL_SPEC = PartialInteractionSpec.model_validate(json.loads({partial_spec_json!r}))


{comment}
def test_{test_name}() -> None:
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
    namespace: dict[str, object] = {{"__name__": "lever_pinned_harness"}}
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
'''


def _test_stem(change_id: str, position: KnobPosition) -> str:
    """Produce a valid, deterministic test name without exposing arbitrary IDs."""
    digest = hashlib.sha256(
        json.dumps(position.root, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    safe_change = "".join(character if character.isalnum() else "_" for character in change_id)
    return f"test_lever_{safe_change[:24]}_{digest}"


def _responsible_comment(
    responsible_line: ResponsibleLine | None,
    repo_root: Path,
    head_path: Path,
) -> str:
    """Keep the dynamic Escape Hatch evidence visible to the future test reader."""
    if responsible_line is None:
        return "# Lever trace attribution: no version-exclusive entry-point line was recorded."
    code = " ".join(responsible_line.code.splitlines())
    source_path = head_path if responsible_line.version == "head" else Path(responsible_line.file)
    return (
        "# Lever trace attribution: "
        f"{_display_path(source_path, repo_root)}:{responsible_line.line} — {code}"
    )


def _source_reference(source_path: Path, repo_root: Path) -> str:
    """Use a branch-relative source path when the pin directory belongs to that branch."""
    try:
        relative = source_path.relative_to(repo_root)
    except ValueError:
        return f"Path({str(source_path)!r})"
    return f"REPO_ROOT / {relative.as_posix()!r}"


def _display_path(source_path: Path, repo_root: Path) -> str:
    """Keep attribution legible after the generated test moves to another checkout."""
    try:
        return source_path.relative_to(repo_root).as_posix()
    except ValueError:
        return str(source_path)
