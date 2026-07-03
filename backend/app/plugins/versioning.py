"""Lightweight semantic-version parsing and dependency matching.

Self-contained (no third-party dependency) so the plugin system can check
plugin versions and declared dependencies without pulling in ``packaging``.
Supports the operators ``>= > <= < == != ~=`` and comma-separated constraints
(e.g. ``">=1.2,<2.0"``). ``~=`` follows PEP 440's compatible-release semantics.
"""
import re
from typing import Optional

_OPERATORS = ("~=", ">=", "<=", "==", "!=", ">", "<")
# A dependency string: "name", "name>=1.0", "name>=1.0,<2.0", "name ==1.2.3".
_NAME_RE = re.compile(r"^([A-Za-z0-9_.\-]+)\s*(.*)$")


def parse_version(version: str) -> tuple:
    """Parse a dotted version string into a comparable tuple of ints.

    Non-numeric suffixes (pre-release/build metadata) are ignored for the
    numeric release comparison, e.g. ``"1.4.0rc1"`` -> ``(1, 4, 0)``.
    """
    if version is None:
        raise ValueError("version cannot be None")
    parts: list[int] = []
    for chunk in str(version).strip().split("."):
        match = re.match(r"\d+", chunk)
        parts.append(int(match.group()) if match else 0)
    return tuple(parts) or (0,)


def _pad(a: tuple, b: tuple) -> tuple:
    """Right-pad the shorter tuple with zeros so they compare positionally."""
    length = max(len(a), len(b))
    return a + (0,) * (length - len(a)), b + (0,) * (length - len(b))


def _compare(version: str, operator: str, target: str) -> bool:
    v = parse_version(version)
    t = parse_version(target)

    if operator == "~=":
        # Compatible release: >= target AND same prefix up to the last component.
        lower = t
        upper = t[:-1]
        upper = upper[:-1] + (upper[-1] + 1,) if upper else (t[0] + 1,)
        vv, ll = _pad(v, lower)
        if vv < ll:
            return False
        vv2, uu = _pad(v, upper)
        return vv2[: len(uu)] < uu

    vv, tt = _pad(v, t)
    if operator == ">=":
        return vv >= tt
    if operator == "<=":
        return vv <= tt
    if operator == ">":
        return vv > tt
    if operator == "<":
        return vv < tt
    if operator == "==":
        return vv == tt
    if operator == "!=":
        return vv != tt
    raise ValueError(f"unknown version operator: {operator!r}")


class Requirement:
    """A parsed dependency requirement, e.g. ``"vector-store>=1.2,<2.0"``."""

    def __init__(self, name: str, constraints: Optional[list[tuple[str, str]]] = None) -> None:
        self.name = name
        #: List of ``(operator, version)`` pairs; empty means "any version".
        self.constraints = constraints or []

    @classmethod
    def parse(cls, spec: str) -> "Requirement":
        match = _NAME_RE.match(spec.strip())
        if not match:
            raise ValueError(f"invalid dependency spec: {spec!r}")
        name, rest = match.group(1), match.group(2).strip()
        constraints: list[tuple[str, str]] = []
        for clause in filter(None, (c.strip() for c in rest.split(","))):
            operator = next((op for op in _OPERATORS if clause.startswith(op)), None)
            if operator is None:
                raise ValueError(f"invalid version constraint in {spec!r}: {clause!r}")
            version = clause[len(operator):].strip()
            if not version:
                raise ValueError(f"missing version in {spec!r}: {clause!r}")
            constraints.append((operator, version))
        return cls(name, constraints)

    def is_satisfied_by(self, version: Optional[str]) -> bool:
        """Whether ``version`` satisfies every constraint (any version if none)."""
        if not self.constraints:
            return True
        if version is None:
            return False
        return all(_compare(version, op, target) for op, target in self.constraints)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        rendered = ",".join(f"{op}{ver}" for op, ver in self.constraints)
        return f"Requirement({self.name}{rendered})"


def satisfies(version: str, spec: str) -> bool:
    """Convenience: does ``version`` satisfy a bare constraint like ``">=1.0"``?"""
    return Requirement.parse(f"_{spec}" if spec[:1] in "<>=~!" else spec).is_satisfied_by(version)
