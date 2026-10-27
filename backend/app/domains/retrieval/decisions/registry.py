from app.config import settings
from app.domains.retrieval.decisions.base import DecisionProvider
from app.domains.retrieval.decisions.jev_provider import JevDecisionProvider
from app.domains.retrieval.decisions.llm_provider import LLMDecisionProvider
from app.domains.retrieval.decisions.rules_provider import RulesDecisionProvider


def get_decision_provider(provider: str | None = None) -> DecisionProvider:
    name = (provider or settings.DECISION_PROVIDER).lower()
    if name == "rules":
        return RulesDecisionProvider()
    if name == "llm":
        return LLMDecisionProvider()
    if name == "jev":
        return JevDecisionProvider()
    raise ValueError(f"Unknown DECISION_PROVIDER '{name}' (expected rules, llm or jev)")
