"""Role definitions and the RBAC hierarchy.

Three roles, ordered by privilege:

* ``admin``     — full control of an organization (members, keys, settings).
* ``developer`` — create/read data and keys, but not manage members.
* ``viewer``    — read-only access.

A role "satisfies" a requirement when it ranks at least as high.
"""


class Role:
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"

    ALL = frozenset({ADMIN, DEVELOPER, VIEWER})
    _RANK = {VIEWER: 1, DEVELOPER: 2, ADMIN: 3}


def is_valid_role(role: str) -> bool:
    return role in Role.ALL


def role_rank(role: str) -> int:
    return Role._RANK.get(role, 0)


def role_satisfies(current: str, required: str) -> bool:
    """True when ``current`` is at least as privileged as ``required``."""
    return role_rank(current) >= role_rank(required)
