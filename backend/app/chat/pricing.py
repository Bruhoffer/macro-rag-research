"""Claude API pricing → estimated USD cost for a chat trace.

Rates are USD per *million* tokens, from the official Anthropic pricing docs
(platform.claude.com/docs/en/about-claude/pricing, verified 2026-06-14).

Note: Anthropic's `usage.input_tokens` already EXCLUDES cached tokens —
cache reads and cache writes (creation) are billed separately at their own
rates, so the cost is the sum of four independent lines.
"""

# USD per million tokens: input | output | cache_read (hit) | cache_write (5-min)
PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {"input": 3.0,  "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-opus-4-8":   {"input": 5.0,  "output": 25.0, "cache_read": 0.50, "cache_write": 6.25},
    "claude-haiku-4-5":  {"input": 1.0,  "output": 5.0,  "cache_read": 0.10, "cache_write": 1.25},
}


def estimate_cost(
    model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    cache_read_tokens: int | None = 0,
    cache_creation_tokens: int | None = 0,
) -> float | None:
    """Estimated USD cost, or None if the model's rates are unknown."""
    rates = PRICING.get(model or "")
    if rates is None:
        return None
    return (
        (input_tokens or 0) * rates["input"]
        + (output_tokens or 0) * rates["output"]
        + (cache_read_tokens or 0) * rates["cache_read"]
        + (cache_creation_tokens or 0) * rates["cache_write"]
    ) / 1_000_000
