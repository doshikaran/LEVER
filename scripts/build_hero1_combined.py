"""Mechanically build Hero 1's AB checkout from B's actual patch applied to A."""

from pathlib import Path

from domain.composed_microworld import apply_unified_patch, unified_diff


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "hero1"


def main() -> None:
    """Emit B's exact unified diff, then apply it to the A checkout."""
    base = (FIXTURES / "base.py").read_text(encoding="utf-8")
    b = (FIXTURES / "limit_head.py").read_text(encoding="utf-8")
    a = (FIXTURES / "head.py").read_text(encoding="utf-8")
    patch = unified_diff(base, b, fromfile="base.py", tofile="limit_head.py")
    (FIXTURES / "limit_multiplier.patch").write_text(patch, encoding="utf-8")
    (FIXTURES / "combined.py").write_text(
        apply_unified_patch(a, patch), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
