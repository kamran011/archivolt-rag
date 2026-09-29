import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import structlog
import tiktoken
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.tracing import RetrievalTrace
from app.domains.agent.retrieval_agent import AgentResult, retrieval_agent
from app.domains.rag.citation_parser import CitationParser
from app.domains.rag.claim_verifier import VerificationOutcome, claim_verifier
from app.domains.rag.conflict_detector import conflict_detector
from app.domains.rag.conflict_resolver import ConflictResolver
from app.domains.rag.prompts import (
    ABSTENTION_TEMPLATE,
    REWRITE_SUPPORTED_ONLY_PROMPT,
    build_context_prompt,
)
from app.domains.rag.schemas import (
    AbstentionReason,
    ClaimVerification,
    ConflictInfo,
    RAGRequest,
    RAGResponse,
    VerificationStatus,
)
from app.domains.retrieval.evidence import ContextAssembler, EvidenceFilter
from app.domains.retrieval.evidence_gate import EvidenceGate
from app.domains.retrieval.expansion import expand_with_neighbors
from app.domains.retrieval.query_router import RouteDecision, query_router
from app.domains.retrieval.schemas import RetrievalRequest, RetrievedChunk
from app.domains.retrieval.service import retrieval_service
from app.providers.cost import estimate_llm_cost
from app.providers.llm.base import LLMProvider
from app.providers.llm.registry import get_llm_provider
from app.providers.reranker.llm_reranker import LLMReranker

logger = structlog.get_logger()

_reranker = LLMReranker()

AGENTIC_MAX_CANDIDATES = 30


class _TokenEstimator:
    def __init__(self) -> None:
        self._encoding = tiktoken.get_encoding("cl100k_base")

    def count(self, text: str) -> int:
        return len(self._encoding.encode(text))


_token_estimate = _TokenEstimator()


@dataclass
class _Retrieved:
    chunks: list[RetrievedChunk]
    retrieval_time_ms: float
    strategy: str
    agent: AgentResult | None = None


async def _retrieve_candidates(
    db: AsyncSession, org_id: uuid.UUID, request: RAGRequest, route: RouteDecision
) -> _Retrieved:
    if request.agentic and settings.ENABLE_AGENTIC_RAG:
        agent = await retrieval_agent.run(db, org_id, request.query, request.knowledge_base_ids)
        return _Retrieved(
            chunks=agent.chunks[:AGENTIC_MAX_CANDIDATES],
            retrieval_time_ms=agent.elapsed_ms,
            strategy="agentic",
            agent=agent,
        )
    result = await retrieval_service.retrieve(
        db,
        org_id,
        RetrievalRequest(
            query=request.query,
            knowledge_base_ids=request.knowledge_base_ids,
            strategy=route.strategy,
            top_k=20,
        ),
    )
    return _Retrieved(result.chunks, result.retrieval_time_ms, result.strategy)


def _route_query(query: str) -> RouteDecision:
    if not settings.ENABLE_ADAPTIVE_ROUTING:
        return RouteDecision(strategy="hybrid", reason="routing disabled")
    return query_router.route(query)


async def _detect_and_resolve_conflicts(
    chunks: list[RetrievedChunk], llm: LLMProvider
) -> list[ConflictInfo]:
    detected = await conflict_detector.detect(chunks, llm)
    resolved: list[ConflictInfo] = []

    for conflict in detected:
        # source_a/source_b are 1-indexed positions in the same numbered
        # source list the LLM was shown (ContextAssembler.format_with_citations).
        if not (1 <= conflict.source_a <= len(chunks) and 1 <= conflict.source_b <= len(chunks)):
            continue  # ignore fabricated source numbers, same rule as citations

        chunk_a = chunks[conflict.source_a - 1]
        chunk_b = chunks[conflict.source_b - 1]
        resolution = ConflictResolver.resolve(
            chunk_a, conflict.source_a, chunk_b, conflict.source_b
        )

        resolved.append(
            ConflictInfo(
                topic=conflict.topic,
                source_a=conflict.source_a,
                claim_a=conflict.claim_a,
                source_b=conflict.source_b,
                claim_b=conflict.claim_b,
                resolved=resolution.resolved,
                winning_source=resolution.winning_source_index,
                resolution_reason=resolution.reason,
            )
        )

    return resolved


@dataclass
class _Finalized:
    """Answer after claim verification and conflict handling."""

    answer: str
    abstained: bool
    reason: AbstentionReason | None
    detail: str | None
    verification_status: VerificationStatus
    claims: list[ClaimVerification]
    conflicts: list[ConflictInfo]


async def _rewrite_supported_only(
    question: str, answer: str, outcome: VerificationOutcome, llm: LLMProvider
) -> str | None:
    """Drop unsupported claims by rewriting from the supported ones. None if nothing
    usable remains or the rewrite fails (callers then fall back to abstaining)."""
    claims = "\n".join(f"- {c.claim}" for c in outcome.supported_claims)
    if not claims:
        return None
    try:
        response = await llm.generate(
            messages=[
                {
                    "role": "user",
                    "content": REWRITE_SUPPORTED_ONLY_PROMPT.format(
                        question=question, claims=claims, answer=answer
                    ),
                }
            ],
            temperature=0.0,
            max_tokens=1024,
        )
    except Exception as e:
        logger.warning("answer_rewrite_failed", error=str(e))
        return None
    text = response.content.strip()
    return None if not text or text.upper() == "NONE" else text


async def _finalize_answer(
    question: str, answer: str, chunks: list[RetrievedChunk], llm: LLMProvider
) -> _Finalized:
    """Claim verification + conflict handling.

    verified -> keep. partial -> rewrite without the unsupported claims (abstain if the
    rewrite is impossible). unsupported -> abstain. unverified (the verifier itself
    failed) -> keep but flag, or abstain when REQUIRE_VERIFICATION is set.
    """
    outcome = await claim_verifier.verify(answer, chunks, llm)
    conflicts = await _detect_and_resolve_conflicts(chunks, llm)

    def abstain(reason: AbstentionReason, detail: str) -> _Finalized:
        return _Finalized(
            answer=ABSTENTION_TEMPLATE.format(reason=detail),
            abstained=True,
            reason=reason,
            detail=detail,
            verification_status=outcome.status,
            claims=outcome.claims,
            conflicts=conflicts,
        )

    if settings.ABSTAIN_ON_UNRESOLVED_CONFLICT and any(not c.resolved for c in conflicts):
        return abstain(
            AbstentionReason.conflicting_sources,
            "The available sources disagree and the disagreement could not be resolved.",
        )

    final_answer, status = answer, outcome.status
    if outcome.status == "unsupported":
        return abstain(
            AbstentionReason.verification_failed,
            "The draft answer could not be supported by the retrieved sources.",
        )
    if outcome.status == "partial":
        rewritten = await _rewrite_supported_only(question, answer, outcome, llm)
        if rewritten is None:
            return abstain(
                AbstentionReason.verification_failed,
                "Parts of the draft answer were not supported by the retrieved sources.",
            )
        final_answer = rewritten
    elif outcome.status == "unverified" and settings.REQUIRE_VERIFICATION:
        return abstain(
            AbstentionReason.verification_failed,
            "The answer could not be verified against the sources.",
        )

    return _Finalized(
        answer=final_answer,
        abstained=False,
        reason=None,
        detail=None,
        verification_status=status,
        claims=outcome.claims,
        conflicts=conflicts,
    )


class RAGService:
    async def query(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        request: RAGRequest,
    ) -> RAGResponse:
        trace = RetrievalTrace(query=request.query, org_id=org_id)
        route = _route_query(request.query)

        # 1. Retrieve
        with trace.span("retrieval", route=route.strategy, route_reason=route.reason):
            retrieval_result = await _retrieve_candidates(db, org_id, request, route)
        candidates = retrieval_result.chunks

        # 2. Rerank
        with trace.span("rerank", candidates_in=len(candidates)):
            reranked = await _reranker.rerank(request.query, candidates, top_k=10)

        # 3. Filter
        with trace.span("filter", candidates_in=len(reranked)):
            filtered = EvidenceFilter.filter_by_score(reranked)
            filtered = EvidenceFilter.deduplicate(filtered)

        # 4. Evidence gate
        with trace.span("evidence_gate", candidates=len(filtered)):
            gate_result = EvidenceGate.evaluate(request.query, filtered)

        retrieval_metadata = {
            "retrieval_time_ms": retrieval_result.retrieval_time_ms,
            "candidates_retrieved": len(candidates),
            "candidates_after_rerank": len(reranked),
            "candidates_after_filter": len(filtered),
            "strategy": retrieval_result.strategy,
        }
        if retrieval_result.agent:
            retrieval_metadata["agent"] = retrieval_result.agent.summary()

        if not gate_result.pass_gate:
            trace.finish(abstained=True, reason=gate_result.reason)
            return RAGResponse(
                answer=ABSTENTION_TEMPLATE.format(reason=gate_result.reason),
                citations=[],
                claim_verifications=[],
                evidence_gate=gate_result,
                abstained=True,
                abstention_reason=AbstentionReason.insufficient_evidence,
                retrieval_metadata=retrieval_metadata,
            )

        # 5. Assemble context
        with trace.span("context_assembly"):
            if settings.ENABLE_NEIGHBOR_EXPANSION:
                filtered = await expand_with_neighbors(db, org_id, filtered)
            selected_chunks, context_tokens = ContextAssembler.assemble(filtered)
            formatted_context = ContextAssembler.format_with_citations(selected_chunks)
        retrieval_metadata["context_tokens"] = context_tokens
        retrieval_metadata["chunks_in_context"] = len(selected_chunks)

        # 6. Generate
        llm = get_llm_provider(request.model)
        messages = [{"role": "system", "content": build_context_prompt(formatted_context)}]
        if request.conversation_history:
            messages.extend(request.conversation_history)
        messages.append({"role": "user", "content": request.query})

        with trace.span("generation", model=request.model):
            llm_response = await llm.generate(messages, temperature=request.temperature)

        retrieval_metadata["prompt_tokens"] = llm_response.prompt_tokens
        retrieval_metadata["completion_tokens"] = llm_response.completion_tokens
        retrieval_metadata["estimated_cost_usd"] = round(
            estimate_llm_cost(
                llm_response.prompt_tokens, llm_response.completion_tokens, request.model
            )
            + (retrieval_result.agent.planner_cost_usd if retrieval_result.agent else 0.0),
            6,
        )

        # 7. Citations
        with trace.span("citation_parsing"):
            citations = CitationParser.parse_citations(llm_response.content, selected_chunks)

        # 8. Claim verification + conflict handling
        with trace.span("claim_verification", claims_checked=len(citations)):
            final = await _finalize_answer(request.query, llm_response.content, selected_chunks, llm)
        if final.abstained:
            citations = []

        trace_summary = trace.finish(
            abstained=final.abstained,
            reason=final.detail,
            verification_status=final.verification_status,
            citations_found=len(citations),
            conflicts_detected=len(final.conflicts),
            estimated_cost_usd=retrieval_metadata["estimated_cost_usd"],
        )
        retrieval_metadata["trace_id"] = trace_summary["trace_id"]
        retrieval_metadata["span_ms"] = trace.to_spans_dict()

        return RAGResponse(
            answer=final.answer,
            citations=citations,
            claim_verifications=final.claims,
            conflicts=final.conflicts,
            evidence_gate=gate_result,
            abstained=final.abstained,
            abstention_reason=final.reason,
            verification_status=final.verification_status,
            retrieval_metadata=retrieval_metadata,
        )

    async def query_stream(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        request: RAGRequest,
    ) -> AsyncIterator[dict]:
        """Same pipeline through context assembly, then streams tokens via SSE-shaped events."""
        trace = RetrievalTrace(query=request.query, org_id=org_id)
        route = _route_query(request.query)

        with trace.span("retrieval", route=route.strategy, route_reason=route.reason):
            retrieval_result = await _retrieve_candidates(db, org_id, request, route)

        with trace.span("rerank", candidates_in=len(retrieval_result.chunks)):
            reranked = await _reranker.rerank(request.query, retrieval_result.chunks, top_k=10)

        with trace.span("filter", candidates_in=len(reranked)):
            filtered = EvidenceFilter.deduplicate(EvidenceFilter.filter_by_score(reranked))

        with trace.span("evidence_gate", candidates=len(filtered)):
            gate_result = EvidenceGate.evaluate(request.query, filtered)

        if not gate_result.pass_gate:
            trace.finish(abstained=True, reason=gate_result.reason)
            abstention_text = ABSTENTION_TEMPLATE.format(reason=gate_result.reason)
            yield {"type": "token", "content": abstention_text}
            yield {
                "type": "done",
                "abstained": True,
                "abstention_reason": AbstentionReason.insufficient_evidence.value,
                "citations": [],
                "evidence_gate": gate_result.model_dump(),
            }
            return

        with trace.span("context_assembly"):
            if settings.ENABLE_NEIGHBOR_EXPANSION:
                filtered = await expand_with_neighbors(db, org_id, filtered)
            selected_chunks, _ = ContextAssembler.assemble(filtered)
            formatted_context = ContextAssembler.format_with_citations(selected_chunks)

        llm = get_llm_provider(request.model)
        messages = [{"role": "system", "content": build_context_prompt(formatted_context)}]
        if request.conversation_history:
            messages.extend(request.conversation_history)
        messages.append({"role": "user", "content": request.query})

        full_answer_parts: list[str] = []
        with trace.span("generation", model=request.model):
            async for token in llm.stream(messages, temperature=request.temperature):
                full_answer_parts.append(token)
                yield {"type": "token", "content": token}

        full_answer = "".join(full_answer_parts)

        with trace.span("citation_parsing"):
            citations = CitationParser.parse_citations(full_answer, selected_chunks)

        with trace.span("claim_verification"):
            final = await _finalize_answer(request.query, full_answer, selected_chunks, llm)
        if final.abstained:
            citations = []

        # Streaming responses don't carry token usage on the wire, so cost is
        # a tiktoken-based estimate rather than the exact figure query() gets.
        prompt_text = "\n".join(m["content"] for m in messages)
        estimated_prompt_tokens = _token_estimate.count(prompt_text)
        estimated_completion_tokens = _token_estimate.count(full_answer)
        estimated_cost = round(
            estimate_llm_cost(estimated_prompt_tokens, estimated_completion_tokens, request.model)
            + (retrieval_result.agent.planner_cost_usd if retrieval_result.agent else 0.0),
            6,
        )

        trace_summary = trace.finish(
            abstained=final.abstained,
            reason=final.detail,
            verification_status=final.verification_status,
            citations_found=len(citations),
            conflicts_detected=len(final.conflicts),
            estimated_cost_usd=estimated_cost,
        )

        yield {
            "type": "done",
            "abstained": final.abstained,
            "abstention_reason": final.reason.value if final.reason else None,
            "verification_status": final.verification_status,
            # Tokens were already streamed; when verification changed the answer the client
            # replaces what it showed with this.
            "final_answer": final.answer if final.answer != full_answer else None,
            "citations": [c.model_dump(mode="json") for c in citations],
            "claim_verifications": [c.model_dump() for c in final.claims],
            "conflicts": [c.model_dump() for c in final.conflicts],
            "evidence_gate": gate_result.model_dump(),
            "cost_metadata": {
                "estimated_prompt_tokens": estimated_prompt_tokens,
                "estimated_completion_tokens": estimated_completion_tokens,
                "estimated_cost_usd": estimated_cost,
                "token_count_method": "estimated",
            },
            "trace_id": trace_summary["trace_id"],
            "span_ms": trace.to_spans_dict(),
            **({"agent": retrieval_result.agent.summary()} if retrieval_result.agent else {}),
        }


rag_service = RAGService()
