"""
Approximate cost estimation for LLM and embedding usage.

Rates are USD per 1M tokens and are illustrative estimates, not billing-grade
figures — they should be kept roughly in sync with provider pricing pages,
but the point of this module is cost *visibility* (spotting an expensive
query pattern, comparing retrieval strategies) rather than exact invoicing.

Per-request cost meter
----------------------
Call ``start_meter()`` at the start of a RAG request to activate the meter for
the current async context.  Every subsequent ``generate()`` call in either LLM
provider then calls ``record_llm_usage()`` to accumulate cost.  Read the total
with ``meter_total_usd()`` after the pipeline finishes.

The meter is opt-in: providers silently skip recording when no meter is active.
Never call ``ContextVar.reset()`` inside an async generator — use the token
returned by ``start_meter()`` only if you need to restore the previous state
from a plain coroutine, not from a generator.

Note: Cohere rerank is a plain HTTP call with no token counts returned, so it
stays unmetered for now.
"""

from contextvars import ContextVar

# (input_per_million, output_per_million) in USD
_LLM_RATES: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-opus-4": (15.00, 75.00),
}
_DEFAULT_LLM_RATE = (2.50, 10.00)  # fall back to gpt-4o-ish pricing for unknown models

_EMBEDDING_RATES: dict[str, float] = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
}
_DEFAULT_EMBEDDING_RATE = 0.02


def _lookup_llm_rate(model: str) -> tuple[float, float]:
    if model.endswith(":free"):  # OpenRouter free-tier models
        return (0.0, 0.0)
    model = model.split("/", 1)[-1]  # OpenRouter ids: "openai/gpt-4o-mini"
    # Longest prefix wins, so "gpt-4o-mini" is not priced as "gpt-4o".
    for known_model in sorted(_LLM_RATES, key=len, reverse=True):
        if model.startswith(known_model):
            return _LLM_RATES[known_model]
    return _DEFAULT_LLM_RATE


def _lookup_embedding_rate(model: str) -> float:
    for known_model, rate in _EMBEDDING_RATES.items():
        if model.startswith(known_model):
            return rate
    return _DEFAULT_EMBEDDING_RATE


def estimate_llm_cost(prompt_tokens: int, completion_tokens: int, model: str) -> float:
    input_rate, output_rate = _lookup_llm_rate(model)
    return (prompt_tokens / 1_000_000) * input_rate + (completion_tokens / 1_000_000) * output_rate


def estimate_embedding_cost(token_count: int, model: str) -> float:
    rate = _lookup_embedding_rate(model)
    return (token_count / 1_000_000) * rate


# ---------------------------------------------------------------------------
# Per-request cost meter
# ---------------------------------------------------------------------------

# Each element is (cost_usd,). A list rather than a float so callers hold a
# reference to the same container across closures.
_active_meter: ContextVar[list[float] | None] = ContextVar("_active_meter", default=None)


def start_meter() -> list[float]:
    """Activate a fresh meter for this async context and return it.

    The returned list accumulates cost and can be read after the pipeline
    finishes.  Keep a reference to it; the ContextVar may be shadowed if a
    nested coroutine calls start_meter() again.
    """
    meter: list[float] = [0.0]
    _active_meter.set(meter)
    return meter


def record_llm_usage(prompt_tokens: int, completion_tokens: int, model: str) -> None:
    """Accumulate cost into the active meter (no-op when no meter is active)."""
    meter = _active_meter.get()
    if meter is not None:
        meter[0] += estimate_llm_cost(prompt_tokens, completion_tokens, model)


def meter_total_usd(meter: list[float]) -> float:
    """Return the accumulated cost from a meter returned by start_meter()."""
    return meter[0]
