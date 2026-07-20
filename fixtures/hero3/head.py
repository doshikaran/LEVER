"""Attribute-based permission check with transitive group inheritance."""

ROLE_PERMISSIONS = {
    "viewer": {"doc"},
    "editor": {"doc", "billing"},
    "admin": {"doc", "billing", "audit-log", "settings"},
    "contractor": {"doc"},
}

ROLE_GROUPS = {
    "contractor": {"contractors"},
}

GROUP_INHERITANCE = {
    "contractors": {"external-readers"},
    "external-readers": {"audit-readers"},
}

GROUP_PERMISSIONS = {
    "audit-readers": {"audit-log"},
}


def can(role: str, action: str, resource: str, same_tenant: bool) -> bool:
    """Allow direct role grants or inherited cross-tenant group grants."""
    if action != "read":
        return False
    if resource in ROLE_PERMISSIONS.get(role, set()):
        return True
    if same_tenant:
        return False

    def inherited_groups() -> set[str]:
        """Resolve every group reachable from this role through the inheritance graph."""
        reachable = set(ROLE_GROUPS.get(role, set()))
        pending = list(reachable)
        while pending:
            group = pending.pop()
            for inherited in GROUP_INHERITANCE.get(group, set()):
                if inherited not in reachable:
                    reachable.add(inherited)
                    pending.append(inherited)
        return reachable

    return any(resource in GROUP_PERMISSIONS.get(group, set()) for group in inherited_groups())
