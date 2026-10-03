from app.config import settings
from app.domains.retrieval.decisions.base import DecisionProvider
from app.domains.retrieval.decisions.rules_provider import RulesDecisionProvider


def get_decision_provider(provider: str | None = None) -> DecisionProvider:
    name = (provider or settings.DECISION_PROVIDER).lower()
    if name == "rules":
        return RulesDecisionProvider()
    # "llm" and "jev" are V2 - registered here once their providers exist.
    raise ValueError(f"Unknown DECISION_PROVIDER '{name}' (expected rules)")
