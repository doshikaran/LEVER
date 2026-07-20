"""Executable reference tests for Hero 3's inherited-group implementation."""

import importlib.util
from pathlib import Path


def _load_head():
    path = Path(__file__).resolve().parents[1] / "head.py"
    spec = importlib.util.spec_from_file_location("hero3_head", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_transitive_group_inheritance_grants_cross_tenant_audit_access() -> None:
    """Contractors reach audit-readers through two group edges inside ``can``."""
    head = _load_head()
    assert head.can("contractor", "read", "audit-log", False)


def test_same_tenant_contractors_do_not_receive_the_cross_tenant_group_grant() -> None:
    """The introduced grant is scoped to the explicitly cross-tenant path."""
    head = _load_head()
    assert not head.can("contractor", "read", "audit-log", True)
