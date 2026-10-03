"""
Approximate cost estimation for LLM and embedding usage.

Rates are USD per 1M tokens and are illustrative estimates, not billing-grade
figures — they should be kept roughly in sync with provider pricing pages,
but the point of this module is cost *visibility* (spotting an expensive
query pattern, comparing retrieval strategies) rather than exact invoicing.
"""

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
    for known_model, rate in _LLM_RATES.items():
        if model.startswith(known_model):
            return rate
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
