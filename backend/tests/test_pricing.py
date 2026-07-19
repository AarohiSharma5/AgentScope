"""Tests for the central, overridable model price table (app.pricing)."""
import pytest

from app import pricing


@pytest.fixture(autouse=True)
def _clear_runtime():
    pricing.clear_runtime_prices()
    yield
    pricing.clear_runtime_prices()


def test_known_model_is_priced():
    cost = pricing.estimate_cost("gpt-4o", 1000, 1000)
    assert cost == pytest.approx(0.0025 + 0.01)
    assert pricing.is_priced("gpt-4o")


def test_unknown_model_is_unpriced_not_zero():
    assert pricing.estimate_cost("mystery-model", 1000, 1000) is None
    assert pricing.is_priced("mystery-model") is False


def test_versioned_name_matches_base_by_prefix():
    # Old exact-match table returned no cost for dated snapshots; prefix match fixes it.
    assert pricing.estimate_cost("gpt-4o-2024-05-13", 1000, 0) == pytest.approx(0.0025)


def test_longest_prefix_wins():
    # gpt-4o-mini must beat gpt-4o for a mini snapshot.
    assert pricing.resolve_price("gpt-4o-mini-2024-07-18") == (0.00015, 0.0006)


def test_runtime_override_takes_precedence():
    pricing.register_prices({"gpt-4o": (1.0, 2.0)})
    assert pricing.estimate_cost("gpt-4o", 1000, 1000) == pytest.approx(3.0)


def test_runtime_can_price_a_custom_model():
    pricing.register_prices({"llama3.2": (0.0, 0.0), "my-model": [0.01, 0.02]})
    assert pricing.is_priced("my-model")
    assert pricing.estimate_cost("my-model", 1000, 1000) == pytest.approx(0.03)
    # zero-priced local model is "priced" (known $0), not unknown.
    assert pricing.estimate_cost("llama3.2", 500, 500) == 0.0


def test_bare_float_is_input_only_price():
    pricing.register_prices({"embed-x": 0.0004})
    assert pricing.estimate_cost("embed-x", 1000, 999) == pytest.approx(0.0004)


def test_malformed_entry_is_ignored():
    pricing.register_prices({"good": (0.001, 0.002), "bad": "not-a-price"})
    assert pricing.is_priced("good")
    assert pricing.is_priced("bad") is False


def test_config_prices_merge_over_defaults(app):
    with app.app_context():
        app.config["MODEL_PRICES"] = {"config-model": [0.005, 0.005]}
        assert pricing.estimate_cost("config-model", 1000, 1000) == pytest.approx(0.01)
        # runtime still beats config
        pricing.register_prices({"config-model": (0.0, 0.0)})
        assert pricing.estimate_cost("config-model", 1000, 1000) == 0.0
