"""Cost-aware model routing: simple questions with small context go to a cheaper model.

Conservative on purpose. It only ever *downgrades* the default model, never overrides a
model the caller explicitly picked, and any signal of difficulty (comparison, calculation,
long/multi-part question, large context) keeps the default.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import settings

_SIMPLE_INTENTS = frozenset({"lookup", "navigation", "chitchat", "general"})
_MAX_SIMPLE_QUESTION_WORDS = 25
_MULTI_PART_MARKERS = (" and also ", " as well as ", "; ", " then ")


@dataclass(frozen=True)
class ModelChoice:
    model: str
    routed: bool
    reason: str


def choose_model(
    requested: str, *, intent: str, query: str, context_tokens: int
) -> ModelChoice:
    cheap = settings.CHEAP_LLM_MODEL
    if not settings.ENABLE_COST_AWARE_ROUTING or not cheap:
        return ModelChoice(requested, False, "routing disabled")
    if requested != settings.DEFAULT_LLM_MODEL:
        return ModelChoice(requested, False, "model chosen explicitly")
    if cheap == requested:
        return ModelChoice(requested, False, "already the cheap model")
    if intent not in _SIMPLE_INTENTS:
        return ModelChoice(requested, False, f"{intent} needs the default model")
    if context_tokens > settings.ROUTING_SIMPLE_MAX_CONTEXT_TOKENS:
        return ModelChoice(requested, False, "large context")
    low = f" {query.lower()} "
    if len(query.split()) > _MAX_SIMPLE_QUESTION_WORDS or any(m in low for m in _MULTI_PART_MARKERS):
        return ModelChoice(requested, False, "long or multi-part question")
    return ModelChoice(cheap, True, "simple question, small context")
