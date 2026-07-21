"""WorldSpec selection is mechanical — genre follows domain pack."""

from domain.schema import InteractionSpec
from domain.synthesizer import synthesize
from domain.world_director import build_world_spec, select_world_genre
from test_synthesizer import _real_hero1_interaction_spec


def test_rate_limiter_maps_to_throughput_arena() -> None:
    spec = _real_hero1_interaction_spec()
    world = build_world_spec(spec)
    assert select_world_genre(spec) == "throughput"
    assert world.genre == "throughput"
    assert world.stage.kind == "arena"
    assert "particles" in world.affordances
    assert len(world.playHints) <= 3
    widget = synthesize(spec)
    assert widget.worldSpec.genre == "throughput"


def test_permission_maps_to_access_matrix() -> None:
    base = _real_hero1_interaction_spec().model_dump(mode="json")
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
    spec = InteractionSpec.model_validate(permission)
    world = build_world_spec(spec)
    assert world.genre == "access-matrix"
    assert world.stage.kind == "matrix"
    assert synthesize(spec).worldSpec.genre == "access-matrix"
