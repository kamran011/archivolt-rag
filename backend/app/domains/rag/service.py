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
from app.domains.rag.stages import build_stages
from app.domains.retrieval.access import AccessScope, Actor
from app.domains.retrieval.analyzer import QueryAnalysis, analyze_query
from app.domains.retrieval.evidence import ContextAssembler, EvidenceFilter
from app.domains.retrieval.evidence_gate import EvidenceGate, EvidenceGateResult
from app.domains.retrieval.expansion import expand_with_neighbors, expand_with_parents
from app.domains.retrieval.query_router import RouteDecision, query_router
from app.domains.retrieval.schemas import RetrievalRequest, RetrievedChunk
from app.domains.retrieval.service import retrieval_service
from app.domains.retrieval.sufficiency import SufficiencyResult, evaluate_sufficiency
from app.providers.cost import estimate_llm_cost
from app.providers.llm.base import LLMProvider
from app.providers.llm.registry import get_llm_provider
from app.providers.reranker.registry import get_reranker

logger = structlog.get_logger()

_reranker = get_reranker()

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
    db: AsyncSession,
    org_id: uuid.UUID,
    request: RAGRequest,
    route: RouteDecision,
    scope: AccessScope | None,
    actor: Actor | None = None,
) -> _Retrieved:
    if request.agentic and settings.ENABLE_AGENTIC_RAG:
        agent = await retrieval_agent.run(
            db,
            org_id,
            request.query,
            request.knowledge_base_ids,
            scope=scope,
            user_id=actor.user_id if actor else None,
            role=actor.role if actor else None,
            org_settings=actor.org_settings if actor else None,
        )
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
        scope=scope,
    )
    return _Retrieved(result.chunks, result.retrieval_time_ms, result.strategy)


@dataclass
class _Evidence:
    """Everything the retrieve -> rerank -> filter -> gates stages produced."""

    retrieval: _Retrieved
    candidates: list[RetrievedChunk]
    reranked: list[RetrievedChunk]
    after_score: list[RetrievedChunk]
    filtered: list[RetrievedChunk]
    filter_drops: list
    gate: EvidenceGateResult
    analysis: QueryAnalysis
    sufficiency: SufficiencyResult
    strategies_tried: list[str]

    @property
    def passed(self) -> bool:
        return self.gate.pass_gate and self.sufficiency.sufficient

    @property
    def abstention_reason(self) -> AbstentionReason:
        if self.gate.pass_gate and self.sufficiency.failure_kind == "outdated":
            return AbstentionReason.outdated
        return AbstentionReason.insufficient_evidence

    @property
    def abstention_detail(self) -> str | None:
        return self.gate.reason if not self.gate.pass_gate else self.sufficiency.reason


def _expansion_ladder(first: str, request: RAGRequest) -> list[RouteDecision]:
    """Strategies to try, in order, when the first attempt is insufficient. Never repeats a
    strategy already tried, and never runs everything: capped by MAX_RETRIEVAL_EXPANSIONS."""
    order: list[RouteDecision] = [RouteDecision(strategy="hybrid", reason="expand: hybrid")]
    if settings.ENABLE_SECTION_SUMMARIES:  # summaries only exist when they are generated
        order.append(RouteDecision(strategy="summary", reason="expand: hierarchical summaries"))
    order.append(RouteDecision(strategy="tree", reason="expand: document tree"))
    ladder = [r for r in order if r.strategy != first]
    return ladder[: max(0, settings.MAX_RETRIEVAL_EXPANSIONS)]


def _merge_candidates(
    existing: list[RetrievedChunk], new: list[RetrievedChunk]
) -> list[RetrievedChunk]:
    seen = {c.chunk_id for c in existing}
    return existing + [c for c in new if c.chunk_id not in seen]


async def _gather_evidence(
    db: AsyncSession,
    org_id: uuid.UUID,
    request: RAGRequest,
    route: RouteDecision,
    trace: RetrievalTrace,
    scope: AccessScope | None,
    actor: Actor | None = None,
) -> _Evidence:
    """Retrieve, rerank, filter and check the evidence; when the sufficiency gate says it
    is not enough, widen retrieval with another strategy (bounded) before giving up.
    Every candidate still comes from org-scoped queries, so expansion cannot widen access."""
    analysis = analyze_query(request.query)
    with trace.span(
        "query_analysis",
        intent=analysis.intent,
        terms=analysis.terms,
        requirements=[r.description for r in analysis.requirements],
    ):
        pass

    with trace.span("retrieval", route=route.strategy, route_reason=route.reason):
        retrieval = await _retrieve_candidates(db, org_id, request, route, scope, actor)
    candidates = list(retrieval.chunks)
    tried = [retrieval.strategy]

    ladder = _expansion_ladder(retrieval.strategy, request) if not request.agentic else []
    attempt = 0
    while True:
        with trace.span("rerank", candidates_in=len(candidates)):
            reranked = await _reranker.rerank(request.query, candidates, top_k=10)
        with trace.span("filter", candidates_in=len(reranked)):
            after_score, outcome = EvidenceFilter.run_pipeline(
                reranked, keep_superseded=analysis.wants_historical
            )
            filtered = outcome.kept
        with trace.span("evidence_gate", candidates=len(filtered)):
            gate = EvidenceGate.evaluate(request.query, filtered)
        with trace.span("sufficiency_gate", attempt=attempt) as span:
            if settings.ENABLE_SUFFICIENCY_GATE and gate.pass_gate:
                sufficiency = evaluate_sufficiency(analysis, filtered)
            else:
                sufficiency = SufficiencyResult(sufficient=True, coverage=1.0, missing=[])
            span.attributes.update(
                sufficient=sufficiency.sufficient,
                coverage=round(sufficiency.coverage, 2),
                missing=sufficiency.missing,
            )

        done = (gate.pass_gate and sufficiency.sufficient) or attempt >= len(ladder)
        if done:
            break
        step = ladder[attempt]
        attempt += 1
        with trace.span("retrieval_expansion", strategy=step.strategy, attempt=attempt):
            extra = await _retrieve_candidates(db, org_id, request, step, scope)
        tried.append(extra.strategy)
        candidates = _merge_candidates(candidates, extra.chunks)

    return _Evidence(
        retrieval=retrieval,
        candidates=candidates,
        reranked=reranked,
        after_score=after_score,
        filtered=filtered,
        filter_drops=outcome.dropped,
        gate=gate,
        analysis=analysis,
        sufficiency=sufficiency,
        strategies_tried=tried,
    )


def _tool_audit(retrieval: _Retrieved) -> list[dict]:
    """Agent tool-call audit records, carried in the internal trace channel to persistence."""
    return [a.model_dump(mode="json") for a in retrieval.agent.tool_audit] if retrieval.agent else []


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
        scope: AccessScope | None = None,
        actor: Actor | None = None,
    ) -> RAGResponse:
        trace = RetrievalTrace(query=request.query, org_id=org_id)
        route = _route_query(request.query)

        # 1-4. Retrieve, rerank, filter, evidence + sufficiency gates (with bounded expansion)
        ev = await _gather_evidence(db, org_id, request, route, trace, scope, actor)
        retrieval_result, candidates = ev.retrieval, ev.candidates
        reranked, after_score, filtered = ev.reranked, ev.after_score, ev.filtered
        gate_result = ev.gate

        retrieval_metadata = {
            "retrieval_time_ms": retrieval_result.retrieval_time_ms,
            "candidates_retrieved": len(candidates),
            "candidates_after_rerank": len(reranked),
            "candidates_after_filter": len(filtered),
            "strategy": retrieval_result.strategy,
            "strategies_tried": ev.strategies_tried,
            "query_intent": ev.analysis.intent,
            "sufficiency": ev.sufficiency.model_dump(),
        }
        if retrieval_result.agent:
            retrieval_metadata["agent"] = retrieval_result.agent.summary()

        if not ev.passed:
            trace_id = trace.finish(abstained=True, reason=ev.abstention_detail)["trace_id"]
            return RAGResponse(
                answer=ABSTENTION_TEMPLATE.format(reason=ev.abstention_detail),
                citations=[],
                claim_verifications=[],
                evidence_gate=gate_result,
                abstained=True,
                abstention_reason=ev.abstention_reason,
                retrieval_metadata={**retrieval_metadata, "trace_id": trace_id},
                trace_stages={
                    **build_stages(
                        candidates=candidates,
                        reranked=reranked,
                        after_score=after_score,
                        filter_drops=ev.filter_drops,
                        filtered=filtered,
                        selected=[],
                        cited_chunk_ids=[],
                    ),
                    "meta": {
                        "strategy": retrieval_result.strategy,
                        "tool_audit": _tool_audit(retrieval_result),
                    },
                },
            )

        # 5. Assemble context
        filtered_before_expansion = filtered
        with trace.span("context_assembly"):
            if settings.ENABLE_NEIGHBOR_EXPANSION:
                filtered = await expand_with_neighbors(db, org_id, filtered, scope=scope)
            if settings.ENABLE_PARENT_EXPANSION:
                filtered = await expand_with_parents(db, org_id, filtered, scope=scope)
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
        trace_stages = build_stages(
            candidates=candidates,
            reranked=reranked,
            after_score=after_score,
            filter_drops=ev.filter_drops,
            filtered=filtered_before_expansion,
            selected=selected_chunks,
            cited_chunk_ids=[c.chunk_id for c in citations],
        )
        trace_stages["meta"] = {
            "spans": trace_summary["spans"],
            "total_ms": trace_summary["total_ms"],
            "strategy": retrieval_result.strategy,
            "tool_audit": _tool_audit(retrieval_result),
        }

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
            trace_stages=trace_stages,
        )

    async def query_stream(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        request: RAGRequest,
        scope: AccessScope | None = None,
        actor: Actor | None = None,
    ) -> AsyncIterator[dict]:
        """Same pipeline through context assembly, then streams tokens via SSE-shaped events."""
        trace = RetrievalTrace(query=request.query, org_id=org_id)
        route = _route_query(request.query)

        ev = await _gather_evidence(db, org_id, request, route, trace, scope, actor)
        retrieval_result = ev.retrieval
        reranked, after_score, filtered = ev.reranked, ev.after_score, ev.filtered
        gate_result = ev.gate

        if not ev.passed:
            trace_id = trace.finish(abstained=True, reason=ev.abstention_detail)["trace_id"]
            abstention_text = ABSTENTION_TEMPLATE.format(reason=ev.abstention_detail)
            yield {"type": "token", "content": abstention_text}
            yield {
                "type": "done",
                "abstained": True,
                "abstention_reason": ev.abstention_reason.value,
                "citations": [],
                "evidence_gate": gate_result.model_dump(),
                "trace_id": trace_id,
                "trace_stages": {
                    **build_stages(
                        candidates=ev.candidates,
                        reranked=reranked,
                        after_score=after_score,
                        filter_drops=ev.filter_drops,
                        filtered=filtered,
                        selected=[],
                        cited_chunk_ids=[],
                    ),
                    "meta": {
                        "strategy": retrieval_result.strategy,
                        "tool_audit": _tool_audit(retrieval_result),
                    },
                },
            }
            return

        filtered_before_expansion = filtered
        with trace.span("context_assembly"):
            if settings.ENABLE_NEIGHBOR_EXPANSION:
                filtered = await expand_with_neighbors(db, org_id, filtered, scope=scope)
            if settings.ENABLE_PARENT_EXPANSION:
                filtered = await expand_with_parents(db, org_id, filtered, scope=scope)
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

        trace_stages = build_stages(
            candidates=ev.candidates,
            reranked=reranked,
            after_score=after_score,
            filter_drops=ev.filter_drops,
            filtered=filtered_before_expansion,
            selected=selected_chunks,
            cited_chunk_ids=[c.chunk_id for c in citations],
        )
        trace_stages["meta"] = {
            "spans": trace_summary["spans"],
            "total_ms": trace_summary["total_ms"],
            "strategy": retrieval_result.strategy,
            "tool_audit": _tool_audit(retrieval_result),
        }

        yield {
            "type": "done",
            "trace_stages": trace_stages,
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
