import time
import uuid
from dataclasses import dataclass
from collections.abc import AsyncIterator

import structlog
import tiktoken
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.tracing import RetrievalTrace
from app.domains.agent.retrieval_agent import AgentResult, retrieval_agent
from app.domains.rag.citation_parser import CitationParser
from app.domains.rag.claim_verifier import claim_verifier
from app.domains.rag.conflict_detector import conflict_detector
from app.domains.rag.conflict_resolver import ConflictResolver
from app.domains.rag.prompts import ABSTENTION_TEMPLATE, build_context_prompt
from app.domains.rag.schemas import ConflictInfo, RAGRequest, RAGResponse
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

        # 8. Claim verification
        with trace.span("claim_verification", claims_checked=len(citations)):
            claim_verifications = await claim_verifier.verify_claims(
                llm_response.content, selected_chunks, llm
            )

        # 9. Conflict detection
        with trace.span("conflict_detection"):
            conflicts = await _detect_and_resolve_conflicts(selected_chunks, llm)

        trace_summary = trace.finish(
            abstained=False,
            citations_found=len(citations),
            conflicts_detected=len(conflicts),
            estimated_cost_usd=retrieval_metadata["estimated_cost_usd"],
        )
        retrieval_metadata["trace_id"] = trace_summary["trace_id"]
        retrieval_metadata["span_ms"] = trace.to_spans_dict()

        return RAGResponse(
            answer=llm_response.content,
            citations=citations,
            claim_verifications=claim_verifications,
            conflicts=conflicts,
            evidence_gate=gate_result,
            abstained=False,
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
            claim_verifications = await claim_verifier.verify_claims(
                full_answer, selected_chunks, llm
            )

        with trace.span("conflict_detection"):
            conflicts = await _detect_and_resolve_conflicts(selected_chunks, llm)

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
            abstained=False,
            citations_found=len(citations),
            conflicts_detected=len(conflicts),
            estimated_cost_usd=estimated_cost,
        )

        yield {
            "type": "done",
            "abstained": False,
            "citations": [c.model_dump(mode="json") for c in citations],
            "claim_verifications": [c.model_dump() for c in claim_verifications],
            "conflicts": [c.model_dump() for c in conflicts],
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
