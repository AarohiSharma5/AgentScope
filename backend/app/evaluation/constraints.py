"""Constraint / validity evaluator (v0.5+).

Lexical metrics (correctness, faithfulness) answer *"does the answer look like
the reference / the context?"* — they can go **green even when the answer
violates a hard product requirement**: it returned jobs needing "0-4 years" when
the ask was "0-3", or listed actors from the wrong film. Those are not overlap
problems; they are *validity* problems, and validity is deterministic.

This module adds a :class:`ConstraintEvaluator` that runs a list of declarative,
dependency-free **constraints** against the evaluation context and emits a single
``constraint_validity`` metric. Constraints are plain JSON-friendly dicts, so
they can be authored per app (in code, config, or later the API) without a custom
Python function each time::

    constraint_evaluator([
        # the answer must not promise years of experience above the ask
        {"type": "numeric_range", "pattern": r"(\\d+)\\s*-\\s*(\\d+)\\s*years",
         "max": 3, "name": "experience_ceiling"},
        # it must stay on the requested sector
        {"type": "contains", "values": ["tech", "software"], "mode": "any",
         "name": "sector"},
        # and never leak an internal tool name
        {"type": "not_contains", "values": ["__debug__"], "severity": "hard"},
    ])

By default a **hard** constraint failure gates the metric to ``0.0`` (so a real
violation can't hide behind other passing checks), and the metric is weighted
heavily so it dominates the overall score. Set ``severity: "soft"`` for advisory
checks that only lower the fraction.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .context import EvaluationContext, MetricResult
from .evaluators import Evaluator, Metrics

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


# -- target + coercion helpers ----------------------------------------------


def _resolve_target(ctx: EvaluationContext, target: Optional[str]) -> Any:
    """Resolve a constraint ``target`` to a context value (default ``answer``)."""
    target = target or "answer"
    if target.startswith("extra."):
        return ctx.extra.get(target[len("extra.") :])
    return getattr(ctx, target, None)


def _as_text(value: Any) -> Optional[str]:
    if value is None or isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)


def _to_number(token: Any) -> Optional[float]:
    try:
        return float(token)
    except (TypeError, ValueError):
        return None


_JSON_TYPES = {
    "string": str,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _json_type_ok(value: Any, type_name: str) -> bool:
    if type_name == "null":
        return value is None
    expected = _JSON_TYPES.get(type_name)
    if expected is None:
        return True  # unknown type spec -> don't fail on it
    if type_name == "number":  # bool is a subclass of int; exclude it
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    return isinstance(value, expected)


# -- compiled constraint ----------------------------------------------------


@dataclass
class _CompiledConstraint:
    name: str
    severity: str  # "hard" | "soft"
    weight: float
    check: Callable[[EvaluationContext], tuple]  # -> (passed: bool, detail: str)


# -- per-type builders (spec dict -> check callable) ------------------------


def _needles(spec: dict, ci: bool):
    values = spec.get("values")
    if values is None and "value" in spec:
        values = [spec["value"]]
    values = [str(v) for v in (values or [])]
    return [v.lower() for v in values] if ci else values, values


def _build_contains(spec: dict):
    target = spec.get("target")
    mode = spec.get("mode", "all")
    ci = spec.get("case_insensitive", True)
    needles, original = _needles(spec, ci)

    def check(ctx):
        text = _as_text(_resolve_target(ctx, target))
        if text is None:
            return False, "no text to check"
        hay = text.lower() if ci else text
        hits = [n for n in needles if n in hay]
        ok = len(hits) > 0 if mode == "any" else len(hits) == len(needles)
        if ok:
            return True, "all present" if mode != "any" else "at least one present"
        missing = [original[i] for i, n in enumerate(needles) if n not in hay]
        return False, f"missing ({mode}): {missing}"

    return check


def _build_not_contains(spec: dict):
    target = spec.get("target")
    ci = spec.get("case_insensitive", True)
    needles, original = _needles(spec, ci)

    def check(ctx):
        text = _as_text(_resolve_target(ctx, target))
        if text is None:
            return True, "no text (vacuously satisfied)"
        hay = text.lower() if ci else text
        present = [original[i] for i, n in enumerate(needles) if n in hay]
        return (not present), ("none present" if not present else f"forbidden present: {present}")

    return check


def _build_regex(spec: dict):
    target = spec.get("target")
    must_match = spec.get("must_match", True)
    flags = re.IGNORECASE if spec.get("case_insensitive") else 0
    rx = re.compile(spec["pattern"], flags)

    def check(ctx):
        text = _as_text(_resolve_target(ctx, target)) or ""
        found = rx.search(text) is not None
        ok = found if must_match else not found
        return ok, f"pattern {'matched' if found else 'not matched'} (must_match={must_match})"

    return check


def _build_numeric_range(spec: dict):
    target = spec.get("target")
    lo = spec.get("min")
    hi = spec.get("max")
    required = spec.get("required", False)
    rx = re.compile(spec["pattern"]) if spec.get("pattern") else None

    def check(ctx):
        text = _as_text(_resolve_target(ctx, target))
        if text is None:
            return (not required), "no text to check"
        numbers = []
        if rx is not None:
            for match in rx.findall(text):
                groups = match if isinstance(match, tuple) else (match,)
                numbers.extend(n for n in (_to_number(g) for g in groups) if n is not None)
        else:
            numbers = [float(t) for t in _NUMBER_RE.findall(text)]
        if not numbers:
            return (not required), "no numbers found"
        bad = [n for n in numbers if (lo is not None and n < lo) or (hi is not None and n > hi)]
        if not bad:
            return True, f"all numbers within [min={lo}, max={hi}]"
        return False, f"out of range {bad} (min={lo}, max={hi})"

    return check


def _build_allowed_values(spec: dict):
    target = spec.get("target")
    ci = spec.get("case_insensitive", True)
    values = [str(v) for v in (spec.get("values") or [])]
    allowed = [v.lower() for v in values] if ci else values
    rx = re.compile(spec["pattern"], re.IGNORECASE if ci else 0) if spec.get("pattern") else None

    def check(ctx):
        text = _as_text(_resolve_target(ctx, target))
        if text is None:
            return False, "no text to check"
        candidate = text.strip()
        if rx is not None:
            match = rx.search(text)
            if match is None:
                return False, "pattern not found"
            candidate = (match.group(1) if match.groups() else match.group(0)).strip()
        cand = candidate.lower() if ci else candidate
        ok = cand in allowed
        return ok, (f"'{candidate}' allowed" if ok else f"'{candidate}' not in {values}")

    return check


def _build_length(spec: dict):
    target = spec.get("target")
    unit = spec.get("unit", "chars")
    lo = spec.get("min")
    hi = spec.get("max")

    def check(ctx):
        text = _as_text(_resolve_target(ctx, target)) or ""
        n = len(text.split()) if unit == "words" else len(text)
        bad = (lo is not None and n < lo) or (hi is not None and n > hi)
        return (not bad), f"{n} {unit} (min={lo}, max={hi})"

    return check


def _build_json_keys(spec: dict):
    target = spec.get("target")
    required = spec.get("required") or []
    types = spec.get("types") or {}

    def check(ctx):
        value = _resolve_target(ctx, target)
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                return False, "not valid JSON"
        if not isinstance(value, dict):
            return False, "not a JSON object"
        missing = [k for k in required if k not in value]
        if missing:
            return False, f"missing keys: {missing}"
        type_errors = [
            f"{k} != {t}" for k, t in types.items() if k in value and not _json_type_ok(value[k], t)
        ]
        return (not type_errors), ("keys/types ok" if not type_errors else f"type errors: {type_errors}")

    return check


def _build_custom(spec: dict):
    fn = spec.get("fn")
    if not callable(fn):
        raise ValueError("custom constraint requires a callable 'fn'")

    def check(ctx):
        out = fn(ctx)
        if isinstance(out, tuple):
            return bool(out[0]), str(out[1]) if len(out) > 1 else "custom predicate"
        return bool(out), "custom predicate"

    return check


_BUILDERS = {
    "contains": _build_contains,
    "not_contains": _build_not_contains,
    "regex": _build_regex,
    "numeric_range": _build_numeric_range,
    "allowed_values": _build_allowed_values,
    "length": _build_length,
    "json_keys": _build_json_keys,
    "custom": _build_custom,
}


def build_constraint(spec: Any) -> _CompiledConstraint:
    """Compile one constraint spec (a dict, a callable, or an already-compiled one)."""
    if isinstance(spec, _CompiledConstraint):
        return spec
    if callable(spec):
        spec = {"type": "custom", "fn": spec}
    if not isinstance(spec, dict):
        raise ValueError(f"constraint must be a dict or callable, got {type(spec).__name__}")
    ctype = spec.get("type")
    builder = _BUILDERS.get(ctype)
    if builder is None:
        raise ValueError(f"unknown constraint type: {ctype!r}; valid: {sorted(_BUILDERS)}")
    return _CompiledConstraint(
        name=spec.get("name") or ctype,
        severity=spec.get("severity", "hard"),
        weight=float(spec.get("weight", 1.0)),
        check=builder(spec),
    )


# -- evaluator --------------------------------------------------------------


class ConstraintEvaluator(Evaluator):
    """Runs declarative constraints and emits one ``constraint_validity`` metric.

    ``value`` is the weight-fraction of constraints satisfied. If any **hard**
    constraint fails and ``gate_on_hard_fail`` is set (default), the value is
    forced to ``0.0`` so a genuine violation can't be averaged away.
    """

    kind = "custom"

    def __init__(
        self,
        constraints: list,
        name: str = Metrics.CONSTRAINT_VALIDITY,
        weight: float = 2.0,
        gate_on_hard_fail: bool = True,
    ) -> None:
        self.name = name
        self.default_weight = weight
        self._gate = gate_on_hard_fail
        self._constraints = [build_constraint(c) for c in (constraints or [])]

    def evaluate(self, ctx: EvaluationContext) -> Optional[MetricResult]:
        if not self._constraints:
            return self._result(None, "no constraints defined")

        results = []
        for constraint in self._constraints:
            try:
                passed, detail = constraint.check(ctx)
            except Exception as exc:  # noqa: BLE001 - a bad check fails closed
                passed, detail = False, f"error: {type(exc).__name__}: {exc}"
            results.append((constraint, bool(passed), detail))

        total_weight = sum(c.weight for c, _, _ in results) or 1.0
        passed_weight = sum(c.weight for c, ok, _ in results if ok)
        hard_failed = [c.name for c, ok, _ in results if not ok and c.severity == "hard"]

        gated = self._gate and bool(hard_failed)
        value = 0.0 if gated else round(passed_weight / total_weight, 4)

        passed_n = sum(1 for _, ok, _ in results if ok)
        failed = [f"{c.name} ({detail})" for c, ok, detail in results if not ok]
        notes = f"{passed_n}/{len(results)} constraints passed"
        if failed:
            notes += "; failed: " + "; ".join(failed[:5])
        if gated:
            notes += f"; gated to 0 by hard failure(s): {hard_failed}"
        return self._result(value, notes[:1000])


def constraint_evaluator(
    constraints: list,
    name: str = Metrics.CONSTRAINT_VALIDITY,
    weight: float = 2.0,
    gate_on_hard_fail: bool = True,
) -> ConstraintEvaluator:
    """Convenience factory mirroring the other evaluator constructors."""
    return ConstraintEvaluator(
        constraints, name=name, weight=weight, gate_on_hard_fail=gate_on_hard_fail
    )


__all__ = ["ConstraintEvaluator", "constraint_evaluator", "build_constraint"]
