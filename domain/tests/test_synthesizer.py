"""Mechanical rate-limiter Synthesizer coverage using the measured Hero 1 result."""

from domain.schema import (
    Agreement,
    Coverage,
    CvStabilityEstimate,
    FidelityReport,
    InteractionSpec,
    KnobPosition,
    Provenance,
    RelativeTolerance,
    Stability,
    SurpriseMarker,
    SymmetristSummary,
)
from domain.entry_point_registry import get_entry_point_template
from domain.synthesizer import synthesize

from test_harness_engineer import _hero_spec


def _real_hero1_interaction_spec() -> InteractionSpec:
    """Reconstitute the measured Hero 1 Phase 4 result for this pure synthesis test."""
    partial = _hero_spec()
    return InteractionSpec(
        specVersion="2.0",
        changeId="hero1-measured-e2b",
        thesis=partial.thesis,
        domainPack=partial.domainPack,
        knobs=partial.knobs,
        observables=partial.observables,
        initialPosition=KnobPosition(
            {
                "limit_per_sec": 100,
                "burst": 1,
                "rps": 100,
                "tenants": 16,
            }
        ),
        surpriseMarker=SurpriseMarker(
            position=KnobPosition(
                {
                    "limit_per_sec": 100,
                    "burst": 1,
                    "rps": 100,
                    "tenants": 16,
                }
            ),
            divergence=0.9380863039399625,
            caption="Head admits 16.0× as many requests (1600 vs 100).",
        ),
        presets=[],
        fidelity=FidelityReport(
            verdict="verified",
            symmetrist=SymmetristSummary(
                passed=True,
                hashA="29976a78901969f70d0ccb373a71773b3d489f970a421a9d6a662ecad1371711",
                hashB="29976a78901969f70d0ccb373a71773b3d489f970a421a9d6a662ecad1371711",
                unjustifiedKeys=[],
            ),
            agreement=Agreement(
                samples=128,
                matched=128,
                rate=1.0,
                tolerance=RelativeTolerance(kind="relative", epsilon=0.01),
            ),
            stability=Stability(
                replicates=12,
                perObservable={"admitted": CvStabilityEstimate(kind="cv", value=0.0)},
            ),
            coverage=Coverage(samples=128, strategy="sobol"),
            confidence=0.8757876680750967,
            band="high",
            degradeReason=None,
        ),
        provenance=Provenance(
            baseSha="hero1-base",
            headSha="hero1-head",
            repoUrl="local://fixtures/hero1",
            generatedAt="1970-01-01T00:00:00Z",
            modelIds={"delta-analyst": "measured"},
            harnessSourceUri="sandbox://hero1/harness",
        ),
    )


def test_synthesizer_maps_the_measured_hero1_spec_to_a_zero_anchored_widget() -> None:
    """The frontend gets all facts it needs without re-reading the InteractionSpec."""
    widget = synthesize(_real_hero1_interaction_spec())

    assert len(widget.controls) == 4
    assert len(widget.charts) == 1
    assert widget.charts[0].render == "timeseries"
    assert widget.charts[0].compareMode == "overlay"
    assert widget.charts[0].yAxisZeroAnchored is True
    assert widget.surpriseMarker is not None
    assert widget.fidelityBand == "high"
    assert widget.fidelityConfidence == 0.8757876680750967


def test_synthesizer_can_render_hero3_permission_and_numeric_fallback_contracts() -> None:
    """A verified Hero 3 proposal never crashes merely because it is not a rate limiter."""
    base = _real_hero1_interaction_spec().model_dump(mode="json")
    template = get_entry_point_template("can")
    assert template is not None and template.numeric_fallback is not None
    numeric_fallback = template.numeric_fallback()

    permission = {
        **base,
        "domainPack": "permission",
        "knobs": [
            {
                "id": "role",
                "label": "role",
                "binding": {"kind": "argument", "fn": "can", "argIndex": 0},
                "type": "enum",
                "domain": {"values": ["contractor"]},
                "default": "contractor",
                "scale": "linear",
                "unit": None,
                "axisRole": "x",
            },
            {
                "id": "resource",
                "label": "resource",
                "binding": {"kind": "argument", "fn": "can", "argIndex": 2},
                "type": "enum",
                "domain": {"values": ["audit-log"]},
                "default": "audit-log",
                "scale": "linear",
                "unit": None,
                "axisRole": "y",
            },
            {
                "id": "same_tenant",
                "label": "same tenant",
                "binding": {"kind": "argument", "fn": "can", "argIndex": 3},
                "type": "boolean",
                "domain": {"values": ["false", "true"]},
                "default": False,
                "scale": "linear",
                "unit": None,
                "axisRole": None,
            },
        ],
        "observables": [
            {
                "id": "allow",
                "label": "allow",
                "extractor": {"kind": "returnValue", "path": "$"},
                "render": "matrixCell",
                "compareMode": "delta",
                "unit": None,
            }
        ],
    }
    fallback = {
        **base,
        "domainPack": numeric_fallback.domainPack.value,
        "knobs": [knob.model_dump(mode="json") for knob in numeric_fallback.knobs],
        "observables": [
            observable.model_dump(mode="json") for observable in numeric_fallback.observables
        ],
    }

    for payload, expected_pack, expected_render in (
        (permission, "permission", "matrixCell"),
        (fallback, "numeric-fn", "scalar"),
    ):
        widget = synthesize(InteractionSpec.model_validate(payload))
        assert widget.domainPack == expected_pack
        assert widget.charts[0].render == expected_render
        assert widget.charts[0].yAxisZeroAnchored is True
