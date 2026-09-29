import json
import math
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.rag.schemas import ClaimVerification, RAGResponse
from app.domains.retrieval.evidence_gate import EvidenceGateResult
from app.domains.retrieval.schemas import RetrievalResult, RetrievedChunk
from app.evals import metrics
from app.evals.dataset import EvalCase, load_dataset
from app.evals.report import CaseResult, compare, summarize
from app.evals.runner import run_eval


def rc(title="Doc", content="text", score=0.5) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(), document_id=uuid.uuid4(), document_title=title,
        content=content, score=score, metadata={}, retrieval_method="hybrid",
    )


def case(**kw) -> EvalCase:
    base = dict(id="c1", question="q", gold_documents=["Refund Policy"])
    return EvalCase(**{**base, **kw})


# ── metrics (hand-computed) ──────────────────────────────────────────────────

def test_relevance_by_title_or_passage_normalised():
    c = case(gold_documents=["refund   policy"], gold_passages=["30  days"])
    assert metrics.is_relevant(rc(title="Refund Policy"), c)
    assert metrics.is_relevant(rc(title="Other", content="within 30 days\nof purchase"), c)
    assert not metrics.is_relevant(rc(title="Other", content="nothing here"), c)


def test_rank_metrics():
    c = case()
    chunks = [rc("A"), rc("B"), rc("Refund Policy"), rc("C")]
    assert metrics.hit_at_k(chunks, c, 2) == 0.0
    assert metrics.hit_at_k(chunks, c, 3) == 1.0
    assert metrics.precision_at_k(chunks, c, 4) == 0.25
    assert metrics.reciprocal_rank(chunks, c) == pytest.approx(1 / 3)
    assert metrics.ndcg_at_k(chunks, c, 4) == pytest.approx((1 / math.log2(4)) / 1.0)


def test_perfect_ranking_scores_one():
    c = case()
    chunks = [rc("Refund Policy"), rc("X")]
    assert metrics.reciprocal_rank(chunks, c) == 1.0
    assert metrics.ndcg_at_k(chunks, c, 2) == 1.0


def test_recall_counts_each_gold_target():
    c = case(gold_documents=["A", "B"], gold_passages=["needle"])
    chunks = [rc("A"), rc("Z", content="a needle in text")]
    assert metrics.recall_at_k(chunks, c, 2) == pytest.approx(2 / 3)
    assert metrics.recall_at_k(chunks, c, 1) == pytest.approx(1 / 3)


def test_no_relevant_results_all_zero():
    c = case()
    chunks = [rc("X"), rc("Y")]
    assert metrics.reciprocal_rank(chunks, c) == 0.0
    assert metrics.ndcg_at_k(chunks, c, 2) == 0.0
    assert metrics.recall_at_k([], c, 5) == 0.0
    assert metrics.precision_at_k([], c, 5) == 0.0


def test_keyword_coverage_and_faithfulness():
    assert metrics.keyword_coverage("Refunds within 30 days", ["30 days", "receipt"]) == 0.5
    assert metrics.keyword_coverage("x", []) is None
    verdicts = [
        ClaimVerification(claim="a", supported=True, supporting_sources=[1], confidence=0.9),
        ClaimVerification(claim="b", supported=False, supporting_sources=[], confidence=0.2),
    ]
    assert metrics.faithfulness(verdicts) == 0.5
    assert metrics.faithfulness([]) is None


# ── dataset ──────────────────────────────────────────────────────────────────

def test_answerable_case_requires_ground_truth():
    with pytest.raises(ValueError, match="gold_documents or gold_passages"):
        EvalCase(id="x", question="q")
    EvalCase(id="x", question="q", should_abstain=True)  # fine


def test_load_dataset_errors_are_located(tmp_path: Path):
    f = tmp_path / "d.jsonl"
    f.write_text('{"id": "a", "question": "q", "gold_documents": ["D"]}\nnot json\n')
    with pytest.raises(ValueError, match=r"d\.jsonl:2"):
        load_dataset(f)

    f.write_text('{"id": "a", "question": "q", "should_abstain": true}\n'
                 '{"id": "a", "question": "q2", "should_abstain": true}\n')
    with pytest.raises(ValueError, match="duplicate case id"):
        load_dataset(f)


def test_sample_dataset_is_valid():
    cases = load_dataset(Path(__file__).parent.parent / "evals" / "datasets" / "sample.jsonl")
    assert len(cases) == 4 and any(c.should_abstain for c in cases)


# ── aggregation & regression gate ────────────────────────────────────────────

def test_summarize_separates_answerable_and_unanswerable():
    results = [
        CaseResult(case_id="a", metrics={"hit_rate": 1.0, "recall": 1.0, "abstention_correct": 1.0,
                                         "latency_ms": 100, "cost_usd": 0.01}),
        CaseResult(case_id="b", metrics={"hit_rate": 0.0, "recall": 0.0, "abstention_correct": 0.0,
                                         "latency_ms": 300, "cost_usd": 0.03}),
        CaseResult(case_id="u1", metrics={"abstention_correct": 1.0, "latency_ms": 50}),
        CaseResult(case_id="u2", metrics={"abstention_correct": 0.0, "latency_ms": 50}),
        CaseResult(case_id="err", metrics={}, error="boom"),
    ]
    flags = {"a": False, "b": False, "u1": True, "u2": True, "err": False}
    s = summarize(results, flags)
    assert s["hit_rate"] == 0.5 and s["recall"] == 0.5  # unanswerable excluded
    assert s["abstention_accuracy"] == 0.5
    assert s["false_answer_rate"] == 0.5     # u2 answered when it should abstain
    assert s["false_abstain_rate"] == 0.5    # b abstained when it should answer
    assert s["avg_latency_ms"] == 125.0      # failed case excluded


def test_compare_flags_regressions_with_tolerance():
    base = {"hit_rate": 0.90, "false_answer_rate": 0.05, "avg_cost_usd": 0.010, "mrr": 0.7}
    cand = {"hit_rate": 0.89, "false_answer_rate": 0.10, "avg_cost_usd": 0.0125, "mrr": 0.8}
    by = {d.metric: d for d in compare(base, cand)}
    assert not by["hit_rate"].regressed        # -0.01 within tolerance
    assert by["false_answer_rate"].regressed   # lower-is-better and it rose
    assert by["avg_cost_usd"].regressed        # +25% > 10%
    assert not by["mrr"].regressed             # improved


def test_compare_skips_metrics_missing_on_either_side():
    assert compare({"hit_rate": None}, {"hit_rate": 0.5}) == []


# ── runner ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def fake_session():
    yield MagicMock()


def rag_response(abstained=False, answer="Refunds take 30 days", cost=0.02):
    return RAGResponse(
        answer=answer, citations=[],
        claim_verifications=[ClaimVerification(claim="c", supported=True,
                                               supporting_sources=[1], confidence=0.9)],
        evidence_gate=EvidenceGateResult(pass_gate=not abstained, confidence=0.9,
                                         top_score=0.9, chunk_count=1),
        abstained=abstained, retrieval_metadata={"estimated_cost_usd": cost},
    )


def retrieval(chunks):
    return RetrievalResult(chunks=chunks, query="q", strategy="hybrid",
                           total_candidates=len(chunks), retrieval_time_ms=1.0)


@pytest.mark.asyncio
async def test_runner_end_to_end_and_failure_isolation():
    cases = [
        case(id="ok", expected_keywords=["30 days"]),
        case(id="unans", gold_documents=[], should_abstain=True),
        case(id="boom"),
    ]

    async def retrieve(db, org, req, embedding_model="x", scope=None):
        if req.query == "explode":
            raise RuntimeError("db down")
        return retrieval([rc("Refund Policy")])

    async def query(db, org, req):
        if req.query == "explode":
            raise RuntimeError("llm down")
        return rag_response(abstained=req.query == "nothing")

    cases[1] = case(id="unans", question="nothing", gold_documents=[], should_abstain=True)
    cases[2] = case(id="boom", question="explode")

    with (
        patch("app.evals.runner.retrieval_service.retrieve", new=retrieve),
        patch("app.evals.runner.rag_service.query", new=query),
    ):
        report = await run_eval(fake_session, uuid.uuid4(), [uuid.uuid4()], cases, k=3)

    by = {r.case_id: r for r in report.cases}
    assert report.total_cases == 3 and report.failed_cases == 1
    assert by["boom"].error is not None
    assert by["ok"].metrics["hit_rate"] == 1.0 and by["ok"].metrics["mrr"] == 1.0
    assert by["ok"].metrics["keyword_coverage"] == 1.0
    assert by["ok"].metrics["faithfulness"] == 1.0 and by["ok"].metrics["cost_usd"] == 0.02
    assert by["unans"].metrics["abstention_correct"] == 1.0
    assert "hit_rate" not in by["unans"].metrics  # no retrieval metrics for unanswerable
    assert report.summary["abstention_accuracy"] == 1.0
    json.loads(report.model_dump_json())  # serialisable for --output


@pytest.mark.asyncio
async def test_runner_retrieval_only_makes_no_llm_calls():
    query = AsyncMock()
    with (
        patch("app.evals.runner.retrieval_service.retrieve",
              new=AsyncMock(return_value=retrieval([rc("Refund Policy")]))),
        patch("app.evals.runner.rag_service.query", new=query),
    ):
        report = await run_eval(fake_session, uuid.uuid4(), [uuid.uuid4()], [case()],
                                retrieval_only=True)
    query.assert_not_called()
    assert report.summary["hit_rate"] == 1.0 and report.summary["avg_latency_ms"] is None


@pytest.mark.asyncio
async def test_runner_false_answer_is_detected():
    with patch("app.evals.runner.rag_service.query",
               new=AsyncMock(return_value=rag_response(abstained=False))):
        report = await run_eval(
            fake_session, uuid.uuid4(), [uuid.uuid4()],
            [case(id="u", gold_documents=[], should_abstain=True)],
        )
    assert report.summary["false_answer_rate"] == 1.0
