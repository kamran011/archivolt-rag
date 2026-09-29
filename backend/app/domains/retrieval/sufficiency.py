"""Sufficiency gate: is the selected evidence enough to answer *this* question?

The evidence gate only asks "is anything relevant-looking?" (a score threshold). This asks
whether the evidence covers what the question needs: its key terms, and freshness/authority
when the question implies them. Term matching is lexical, so a very confident reranker
score can override it (synonyms: "refund window" vs "return period").
"""

from __future__ import annotations

from pydantic import BaseModel

from app.config import settings
from app.domains.retrieval.analyzer import QueryAnalysis
from app.domains.retrieval.schemas import RetrievedChunk


class SufficiencyResult(BaseModel):
    sufficient: bool
    coverage: float
    missing: list[str]
    reason: str | None = None
    # 'outdated' when the only thing wrong is freshness, else 'insufficient_evidence'.
    failure_kind: str | None = None


def _stem(word: str) -> str:
    for suffix in ("ies", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def _covers(term: str, haystack: str) -> bool:
    return term in haystack or _stem(term) in haystack


def evaluate_sufficiency(
    analysis: QueryAnalysis,
    chunks: list[RetrievedChunk],
    *,
    min_coverage: float | None = None,
    high_confidence: float | None = None,
) -> SufficiencyResult:
    min_cov = settings.SUFFICIENCY_MIN_COVERAGE if min_coverage is None else min_coverage
    high = settings.SUFFICIENCY_HIGH_CONFIDENCE if high_confidence is None else high_confidence

    if analysis.intent == "chitchat":
        return SufficiencyResult(sufficient=True, coverage=1.0, missing=[])
    if not chunks:
        return SufficiencyResult(
            sufficient=False,
            coverage=0.0,
            missing=[r.description for r in analysis.requirements],
            reason="No evidence was selected",
            failure_kind="insufficient_evidence",
        )

    haystack = " ".join(c.content.lower() for c in chunks)
    top_score = max(c.score for c in chunks)

    term_reqs = [r for r in analysis.requirements if r.kind == "term"]
    missing_terms = [r.value for r in term_reqs if not _covers(r.value, haystack)]
    coverage = 1.0 if not term_reqs else 1 - len(missing_terms) / len(term_reqs)

    if analysis.wants_current and not any(c.is_current for c in chunks):
        return SufficiencyResult(
            sufficient=False,
            coverage=coverage,
            missing=["current version"],
            reason="The question asks about the current state but only superseded "
            "documents were found",
            failure_kind="outdated",
        )
    if analysis.wants_authoritative and all(c.authority_tier == "draft" for c in chunks):
        return SufficiencyResult(
            sufficient=False,
            coverage=coverage,
            missing=["authoritative source"],
            reason="Only draft (unreviewed) sources were found for a policy-type question",
            failure_kind="insufficient_evidence",
        )

    if coverage >= min_cov or top_score >= high:
        return SufficiencyResult(sufficient=True, coverage=coverage, missing=missing_terms)

    return SufficiencyResult(
        sufficient=False,
        coverage=coverage,
        missing=missing_terms,
        reason=(
            f"The evidence does not mention key parts of the question: "
            f"{', '.join(missing_terms)}"
        ),
        failure_kind="insufficient_evidence",
    )
