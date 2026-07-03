"""Cost estimation from per-model price tables.

Price tables are plain data owned by each provider adapter (``{model: (input,
output)}`` in USD per 1K tokens). Keeping the math here means every provider
estimates cost the same way, and unknown models simply return ``None`` rather
than guessing.
"""
from typing import Optional


def estimate_cost(
    pricing: dict,
    model: Optional[str],
    input_tokens: Optional[int],
    output_tokens: Optional[int],
) -> Optional[float]:
    """Estimate USD cost for a call, or ``None`` if the model is unpriced.

    ``pricing`` maps a model name to ``(input_per_1k, output_per_1k)``. A single
    float is accepted as shorthand for an input-only price (e.g. embeddings).
    """
    if not model or not pricing:
        return None
    entry = pricing.get(model)
    if entry is None:
        return None
    if isinstance(entry, (int, float)):
        input_price, output_price = float(entry), 0.0
    else:
        input_price, output_price = entry
    cost = (input_tokens or 0) / 1000 * input_price + (output_tokens or 0) / 1000 * output_price
    return round(cost, 8)
