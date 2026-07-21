"""Unit tests for the constraint / validity evaluator (no DB required)."""
import pytest

from app.evaluation import Metrics, build_constraint, constraint_evaluator
from app.evaluation.context import EvaluationContext


def _ctx(answer=None, **kwargs):
    return EvaluationContext(conversation_run_id=1, answer=answer, **kwargs)


def _run(spec, ctx):
    """Run a single compiled constraint, returning (passed, detail)."""
    return build_constraint(spec).check(ctx)


# -- individual constraint types --------------------------------------------


def test_contains_all_and_any():
    ctx = _ctx("jobs in tech and software")
    assert _run({"type": "contains", "values": ["tech", "software"]}, ctx)[0] is True
    assert _run({"type": "contains", "values": ["tech", "finance"]}, ctx)[0] is False
    assert _run({"type": "contains", "values": ["tech", "finance"], "mode": "any"}, ctx)[0] is True


def test_not_contains():
    ctx = _ctx("safe answer")
    assert _run({"type": "not_contains", "values": ["__debug__"]}, ctx)[0] is True
    leaky = _ctx("internal __debug__ leaked")
    assert _run({"type": "not_contains", "values": ["__debug__"]}, leaky)[0] is False


def test_not_contains_vacuous_when_no_text():
    assert _run({"type": "not_contains", "values": ["x"]}, _ctx(None))[0] is True


def test_regex_must_match_and_must_not():
    ctx = _ctx("Order #12345 confirmed")
    assert _run({"type": "regex", "pattern": r"#\d+"}, ctx)[0] is True
    assert _run({"type": "regex", "pattern": r"#\d+", "must_match": False}, ctx)[0] is False


def test_numeric_range_catches_experience_ceiling():
    # The ask was "0-3 years"; the answer promises "0-4 years" -> violation.
    ctx = _ctx("Roles requiring 0-4 years of experience.")
    spec = {"type": "numeric_range", "pattern": r"(\d+)\s*-\s*(\d+)\s*years", "max": 3}
    passed, detail = _run(spec, ctx)
    assert passed is False and "out of range" in detail

    ok = _ctx("Roles requiring 0-3 years of experience.")
    assert _run(spec, ok)[0] is True


def test_numeric_range_no_pattern_scans_all_numbers():
    assert _run({"type": "numeric_range", "min": 0, "max": 10}, _ctx("scores 3 and 7"))[0] is True
    assert _run({"type": "numeric_range", "min": 0, "max": 5}, _ctx("scores 3 and 7"))[0] is False


def test_numeric_range_required_when_missing():
    spec = {"type": "numeric_range", "pattern": r"(\d+) years", "max": 3, "required": True}
    assert _run(spec, _ctx("no numbers here"))[0] is False
    # required=False (default) is lenient when nothing matches
    assert _run({**spec, "required": False}, _ctx("no numbers here"))[0] is True


def test_allowed_values_with_extraction():
    spec = {"type": "allowed_values", "pattern": r"sentiment:\s*(\w+)", "values": ["positive", "negative"]}
    assert _run(spec, _ctx("sentiment: positive"))[0] is True
    assert _run(spec, _ctx("sentiment: angry"))[0] is False


def test_length_words_and_chars():
    ctx = _ctx("one two three four five")
    assert _run({"type": "length", "unit": "words", "max": 5}, ctx)[0] is True
    assert _run({"type": "length", "unit": "words", "max": 3}, ctx)[0] is False
    assert _run({"type": "length", "min": 100}, ctx)[0] is False


def test_json_keys_and_types():
    ctx = _ctx('{"name": "x", "count": 3}')
    assert _run({"type": "json_keys", "required": ["name", "count"]}, ctx)[0] is True
    assert _run({"type": "json_keys", "required": ["missing"]}, ctx)[0] is False
    assert _run({"type": "json_keys", "types": {"count": "number"}}, ctx)[0] is True
    assert _run({"type": "json_keys", "types": {"count": "string"}}, ctx)[0] is False
    assert _run({"type": "json_keys", "required": []}, _ctx("not json"))[0] is False


def test_target_can_point_at_other_context_fields():
    ctx = _ctx("answer", user_prompt="find tech jobs", extra={"category": "sales"})
    assert _run({"type": "contains", "values": ["tech"], "target": "user_prompt"}, ctx)[0] is True
    assert _run({"type": "allowed_values", "values": ["tech"], "target": "extra.category"}, ctx)[0] is False


def test_custom_callable_constraint():
    ctx = _ctx("hello")
    assert _run(lambda c: c.answer == "hello", ctx)[0] is True
    assert _run({"type": "custom", "fn": lambda c: (False, "nope")}, ctx) == (False, "nope")


def test_unknown_type_raises():
    with pytest.raises(ValueError):
        build_constraint({"type": "does_not_exist"})


# -- the evaluator (aggregation + gating) -----------------------------------


def test_evaluator_fraction_without_gate():
    ev = constraint_evaluator(
        [
            {"type": "contains", "values": ["a"], "severity": "soft"},
            {"type": "contains", "values": ["zzz"], "severity": "soft"},
        ],
        gate_on_hard_fail=True,
    )
    result = ev.evaluate(_ctx("a b c"))
    assert result.name == Metrics.CONSTRAINT_VALIDITY
    assert result.value == 0.5  # one of two soft checks passed, no hard fail
    assert "1/2" in result.notes


def test_evaluator_gates_to_zero_on_hard_failure():
    ev = constraint_evaluator(
        [
            {"type": "contains", "values": ["a"]},  # passes
            {"type": "contains", "values": ["zzz"], "severity": "hard"},  # fails hard
        ]
    )
    result = ev.evaluate(_ctx("a b c"))
    assert result.value == 0.0
    assert "gated to 0" in result.notes


def test_evaluator_weighting_between_constraints():
    ev = constraint_evaluator(
        [
            {"type": "contains", "values": ["a"], "weight": 3, "severity": "soft"},
            {"type": "contains", "values": ["zzz"], "weight": 1, "severity": "soft"},
        ]
    )
    # 3 of 4 weight satisfied
    assert ev.evaluate(_ctx("a b c")).value == 0.75


def test_evaluator_all_pass_is_one():
    ev = constraint_evaluator([{"type": "contains", "values": ["a"]}])
    assert ev.evaluate(_ctx("a")).value == 1.0


def test_empty_constraints_is_not_applicable():
    result = constraint_evaluator([]).evaluate(_ctx("x"))
    assert result.value is None
    assert "no constraints" in result.notes


def test_default_weight_is_heavy():
    assert constraint_evaluator([{"type": "contains", "values": ["a"]}]).default_weight == 2.0
