"""Jev DecisionProvider: evidence sufficiency judged by TypeSafe's Jev (System One).

Decision flow (all code, Jev only supplies the judgment):
1. Rules run first. Freshness ("only superseded versions found") and authority ("only
   drafts") are facts code already knows, so those verdicts are final.
2. Jev is asked whether the selected passages state what the question asks (one Noul,
   see jev_questions.py), and `decide()` maps the probability to sufficient /
   insufficient / unsettled. Unsettled keeps the rules verdict.
3. A failed Jev call is not an answer: it is logged and the rules verdict stands.
Only passages that already passed access control for this caller are sent.
"""

from __future__ import annotations

import httpx
import structlog

from app.domains.retrieval.analyzer import QueryAnalysis
from app.domains.retrieval.decisions import jev_questions as jq
from app.domains.retrieval.decisions.base import DecisionProvider
from app.domains.retrieval.decisions.rules_provider import RulesDecisionProvider
from app.domains.retrieval.schemas import RetrievedChunk
from app.domains.retrieval.sufficiency import SufficiencyResult
from app.providers.typesafe import client as typesafe

logger = structlog.get_logger()

_CODE_DECIDED = (["current version"], ["authoritative source"])


class JevDecisionProvider(DecisionProvider):
    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._http = http_client
        self._rules = RulesDecisionProvider()

    async def evaluate_sufficiency(
        self,
        analysis: QueryAnalysis,
        chunks: list[RetrievedChunk],
        *,
        min_coverage: float | None = None,
        high_confidence: float | None = None,
    ) -> SufficiencyResult:
        rules = await self._rules.evaluate_sufficiency(
            analysis, chunks, min_coverage=min_coverage, high_confidence=high_confidence
        )
        if (
            not typesafe.configured()
            or not chunks
            or analysis.intent == "chitchat"
            or not analysis.query
            or rules.failure_kind == "outdated"
            or rules.missing in _CODE_DECIDED
        ):
            return rules

        try:
            response = await typesafe.system_one(
                jq.build_state(analysis.query, chunks), jq.QUESTIONS, client=self._http
            )
            p = response.noul(jq.STATES_ANSWER)
        except typesafe.TypeSafeError as e:
            logger.warning("jev_decision_failed", error=str(e))
            return rules

        verdict = jq.decide(p)
        logger.info("jev_decision", states_answer=round(p, 3), verdict=verdict.value,
                    rules_sufficient=rules.sufficient, model=response.model)
        if verdict is jq.Verdict.sufficient:
            return SufficiencyResult(
                sufficient=True,
                coverage=rules.coverage,
                missing=[],
                reason=f"Jev: passages state the answer (p={p:.2f})",
            )
        if verdict is jq.Verdict.insufficient:
            return SufficiencyResult(
                sufficient=False,
                coverage=rules.coverage,
                missing=rules.missing or ["the requested information"],
                reason=f"Jev: passages do not state the answer (p={p:.2f})",
                failure_kind="insufficient_evidence",
            )
        return rules
