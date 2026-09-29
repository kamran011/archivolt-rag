import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.domains.rag.claim_verifier import ClaimVerifier, summarize_status
from app.domains.rag.schemas import AbstentionReason, ClaimVerification, ConflictInfo, RAGRequest
from app.domains.rag.service import RAGService, _finalize_answer
from app.domains.retrieval.schemas import RetrievalResult, RetrievedChunk
from app.providers.llm.base import LLMResponse


def chunk(content="Refunds are allowed within 30 days.", score=0.9) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="Policy",
        content=content,
        score=score,
        metadata={},
        retrieval_method="hybrid",
    )


def claim(status: str, text: str = "c") -> ClaimVerification:
    return ClaimVerification(
        claim=text,
        supported=status == "supported",
        status=status,
        supporting_sources=[1],
        confidence=0.9,
    )


class ScriptedLLM:
    """Returns queued responses in order; a queued Exception is raised instead."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    async def generate(self, messages, temperature=0.1, max_tokens=2048):
        self.calls += 1
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return LLMResponse(
            content=r, prompt_tokens=1, completion_tokens=1, model="fake", finish_reason="stop"
        )


def claims_json(*items) -> str:
    return json.dumps(
        [
            {"claim": t, "status": s, "supporting_sources": [1], "confidence": 0.9}
            for t, s in items
        ]
    )


# --- summarize_status / parsing -------------------------------------------------


def test_summarize_status():
    assert summarize_status([]) == "unverified"
    assert summarize_status([claim("supported"), claim("supported")]) == "verified"
    assert summarize_status([claim("supported"), claim("unsupported")]) == "partial"
    assert summarize_status([claim("unsupported"), claim("unsupported")]) == "unsupported"
    assert summarize_status([claim("partial")]) == "partial"


def test_parse_new_and_legacy_shapes():
    v = ClaimVerifier()
    new = v._parse_verifications(claims_json(("a", "partial"), ("b", "unsupported")))
    assert [c.status for c in new] == ["partial", "unsupported"]
    assert [c.supported for c in new] == [False, False]

    legacy = v._parse_verifications(
        '[{"claim": "a", "supported": true, "supporting_sources": [1], "confidence": 1}]'
    )
    assert legacy[0].status == "supported" and legacy[0].supported is True


@pytest.mark.asyncio
async def test_verifier_failure_is_unverified_not_a_pass():
    v = ClaimVerifier()
    err = await v.verify("answer", [chunk()], ScriptedLLM(RuntimeError("boom")))
    assert err.status == "unverified"
    garbage = await v.verify("answer", [chunk()], ScriptedLLM("not json"))
    assert garbage.status == "unverified"


# --- _finalize_answer policy -----------------------------------------------------


async def finalize(llm, conflicts=None, answer="draft answer"):
    with patch(
        "app.domains.rag.service._detect_and_resolve_conflicts",
        new=AsyncMock(return_value=conflicts or []),
    ):
        return await _finalize_answer("question?", answer, [chunk()], llm)


@pytest.mark.asyncio
async def test_verified_answer_is_kept():
    f = await finalize(ScriptedLLM(claims_json(("x", "supported"))))
    assert not f.abstained and f.answer == "draft answer"
    assert f.verification_status == "verified"


@pytest.mark.asyncio
async def test_partial_answer_is_rewritten_without_unsupported_claims():
    llm = ScriptedLLM(
        claims_json(("kept", "supported"), ("invented", "unsupported")),
        "Only the supported part [Source 1].",
    )
    f = await finalize(llm)
    assert not f.abstained
    assert f.answer == "Only the supported part [Source 1]."
    assert f.verification_status == "partial"


@pytest.mark.asyncio
async def test_partial_with_failed_rewrite_abstains():
    llm = ScriptedLLM(
        claims_json(("kept", "supported"), ("invented", "unsupported")), RuntimeError("down")
    )
    f = await finalize(llm)
    assert f.abstained and f.reason == AbstentionReason.verification_failed


@pytest.mark.asyncio
async def test_partial_with_nothing_supported_left_abstains():
    # 'partial' status claims only -> no supported claims to rewrite from.
    f = await finalize(ScriptedLLM(claims_json(("half", "partial"))))
    assert f.abstained and f.reason == AbstentionReason.verification_failed


@pytest.mark.asyncio
async def test_fully_unsupported_answer_abstains():
    f = await finalize(
        ScriptedLLM(claims_json(("a", "unsupported"), ("b", "unsupported"))),
        answer="INVENTED-ANSWER-TEXT",
    )
    assert f.abstained and f.reason == AbstentionReason.verification_failed
    assert "INVENTED-ANSWER-TEXT" not in f.answer


@pytest.mark.asyncio
async def test_unverified_is_flagged_by_default(monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_VERIFICATION", False)
    f = await finalize(ScriptedLLM(RuntimeError("verifier down")))
    assert not f.abstained and f.verification_status == "unverified"


@pytest.mark.asyncio
async def test_unverified_abstains_when_verification_required(monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_VERIFICATION", True)
    f = await finalize(ScriptedLLM(RuntimeError("verifier down")))
    assert f.abstained and f.reason == AbstentionReason.verification_failed


def unresolved() -> ConflictInfo:
    return ConflictInfo(
        topic="refund", source_a=1, claim_a="30d", source_b=2, claim_b="60d", resolved=False
    )


@pytest.mark.asyncio
async def test_unresolved_conflict_is_exposed_but_answers_by_default(monkeypatch):
    monkeypatch.setattr(settings, "ABSTAIN_ON_UNRESOLVED_CONFLICT", False)
    f = await finalize(ScriptedLLM(claims_json(("x", "supported"))), [unresolved()])
    assert not f.abstained and len(f.conflicts) == 1


@pytest.mark.asyncio
async def test_unresolved_conflict_abstains_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "ABSTAIN_ON_UNRESOLVED_CONFLICT", True)
    f = await finalize(ScriptedLLM(claims_json(("x", "supported"))), [unresolved()])
    assert f.abstained and f.reason == AbstentionReason.conflicting_sources
    assert len(f.conflicts) == 1


# --- end to end through RAGService ------------------------------------------------


@pytest.mark.asyncio
async def test_query_drops_citations_and_reports_reason_on_verification_abstain():
    c = chunk()
    llm = ScriptedLLM(
        "Refunds take 90 days [Source 1].",  # generation
        claims_json(("Refunds take 90 days", "unsupported")),  # verifier
    )
    with patch(
        "app.domains.rag.service.retrieval_service.retrieve",
        new=AsyncMock(
            return_value=RetrievalResult(
                chunks=[c], query="q", strategy="hybrid", total_candidates=1, retrieval_time_ms=1.0
            )
        ),
    ), patch(
        "app.domains.rag.service._reranker.rerank", new=AsyncMock(return_value=[c])
    ), patch("app.domains.rag.service.get_llm_provider", return_value=llm), patch(
        "app.domains.rag.service._detect_and_resolve_conflicts", new=AsyncMock(return_value=[])
    ):
        response = await RAGService().query(
            db=AsyncMock(),
            org_id=uuid.uuid4(),
            request=RAGRequest(query="refund window?", knowledge_base_ids=[uuid.uuid4()]),
        )

    assert response.abstained is True
    assert response.abstention_reason == AbstentionReason.verification_failed
    assert response.citations == []
    assert "90 days" not in response.answer


@pytest.mark.asyncio
async def test_gate_abstention_carries_insufficient_evidence_reason():
    with patch(
        "app.domains.rag.service.retrieval_service.retrieve",
        new=AsyncMock(
            return_value=RetrievalResult(
                chunks=[], query="q", strategy="hybrid", total_candidates=0, retrieval_time_ms=1.0
            )
        ),
    ):
        response = await RAGService().query(
            db=AsyncMock(),
            org_id=uuid.uuid4(),
            request=RAGRequest(query="unknown?", knowledge_base_ids=[uuid.uuid4()]),
        )
    assert response.abstained and response.abstention_reason == AbstentionReason.insufficient_evidence
