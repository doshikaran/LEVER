"""Executable reference tests for Hero 3's flat role-table baseline."""

import importlib.util
from pathlib import Path


def _load_base():
    path = Path(__file__).resolve().parents[1] / "base.py"
    spec = importlib.util.spec_from_file_location("hero3_base", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_flat_table_preserves_direct_admin_access() -> None:
    """The pre-change table allows direct role grants only."""
    base = _load_base()
    assert base.can("admin", "read", "audit-log", False)
    assert not base.can("contractor", "read", "audit-log", False)


def test_flat_table_rejects_unknown_actions() -> None:
    """A role permission does not authorize a different action."""
    base = _load_base()
    assert not base.can("admin", "write", "settings", True)
