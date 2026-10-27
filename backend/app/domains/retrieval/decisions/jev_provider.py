"""Jev DecisionProvider: delegates the sufficiency decision to an external Jev service.

Contract (JSON over HTTPS, `Authorization: Bearer $JEV_API_KEY`):

  POST $JEV_ENDPOINT
  {"question": str, "intent": str, "terms": [str], "wants_current": bool,
   "wants_authoritative": bool,
   "passages": [{"id": str, "text": str, "score": float, "is_current": bool}],
   "rules_verdict": {"sufficient": bool, "coverage": float, "missing": [str]}}

  200 -> {"sufficient": bool, "coverage": float (optional), "missing": [str] (optional),
          "reason": str (optional)}

The rules verdict is always sent and is the fallback: a missing endpoint, timeout, non-200
or malformed reply returns the rules result, so the gate never depends on Jev being up.
Only passage text already allowed for this caller (post access-control) is sent.
"""

from __future__ import annotations

import httpx
import structlog

from app.config import settings
from app.domains.retrieval.analyzer import QueryAnalysis
from app.domains.retrieval.decisions.base import DecisionProvider
from app.domains.retrieval.decisions.rules_provider import RulesDecisionProvider
from app.domains.retrieval.schemas import RetrievedChunk
from app.domains.retrieval.sufficiency import SufficiencyResult

logger = structlog.get_logger()

MAX_PASSAGES = 8
MAX_PASSAGE_CHARS = 1200


class JevDecisionProvider(DecisionProvider):
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
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
        if not settings.JEV_ENDPOINT or analysis.intent == "chitchat":
            return rules
        payload = {
            "question": analysis.query,
            "intent": analysis.intent,
            "terms": analysis.terms,
            "wants_current": analysis.wants_current,
            "wants_authoritative": analysis.wants_authoritative,
            "passages": [
                {
                    "id": str(c.chunk_id),
                    "text": c.content[:MAX_PASSAGE_CHARS],
                    "score": c.score,
                    "is_current": c.is_current,
                }
                for c in chunks[:MAX_PASSAGES]
            ],
            "rules_verdict": {
                "sufficient": rules.sufficient,
                "coverage": rules.coverage,
                "missing": rules.missing,
            },
        }
        headers = {"Authorization": f"Bearer {settings.JEV_API_KEY}"} if settings.JEV_API_KEY else {}
        try:
            if self._client is not None:
                resp = await self._client.post(settings.JEV_ENDPOINT, json=payload, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=settings.JEV_TIMEOUT_S) as client:
                    resp = await client.post(settings.JEV_ENDPOINT, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("jev_decision_failed", error=str(e))
            return rules
        if not isinstance(data, dict) or not isinstance(data.get("sufficient"), bool):
            logger.warning("jev_decision_malformed")
            return rules
        missing = data.get("missing")
        reason = data.get("reason")
        coverage = data.get("coverage")
        return SufficiencyResult(
            sufficient=data["sufficient"],
            coverage=float(coverage) if isinstance(coverage, int | float) else rules.coverage,
            missing=[str(m)[:200] for m in missing][:5] if isinstance(missing, list) else [],
            reason=reason[:300] if isinstance(reason, str) else None,
            failure_kind=None if data["sufficient"] else (rules.failure_kind or "insufficient_evidence"),
        )
