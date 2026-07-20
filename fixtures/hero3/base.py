"""Flat role-table permission check before attribute/group inheritance."""

ROLE_PERMISSIONS = {
    "viewer": {"doc"},
    "editor": {"doc", "billing"},
    "admin": {"doc", "billing", "audit-log", "settings"},
    "contractor": {"doc"},
}


def can(role: str, action: str, resource: str, same_tenant: bool) -> bool:
    """Return whether a role may perform an action on a resource in this tenant scope."""
    if action != "read":
        return False
    return resource in ROLE_PERMISSIONS.get(role, set())
