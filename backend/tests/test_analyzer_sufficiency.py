import uuid

import pytest

from app.domains.retrieval.analyzer import analyze_query
from app.domains.retrieval.schemas import RetrievedChunk
from app.domains.retrieval.sufficiency import evaluate_sufficiency


def chunk(content, score=0.5, is_current=True, tier="standard") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="d",
        content=content,
        score=score,
        metadata={},
        retrieval_method="hybrid",
        is_current=is_current,
        authority_tier=tier,
    )


# --- analyzer ---------------------------------------------------------------------


def test_refund_policy_example_from_the_spec():
    a = analyze_query("What is the company's current refund policy for annual plans?")
    assert a.intent == "lookup"
    assert a.wants_current and a.wants_authoritative
    assert {"refund", "annual", "plans"} <= set(a.terms)
    kinds = {r.kind for r in a.requirements}
    assert kinds == {"term", "current", "authoritative"}


def test_stopwords_and_short_tokens_are_not_terms():
    a = analyze_query("What is the of and to it")
    assert a.terms == []


def test_terms_are_deduplicated_and_capped():
    a = analyze_query("refund refund refund " + " ".join(f"word{i}xyz" for i in range(20)))
    assert a.terms.count("refund") == 1 and len(a.terms) <= 6


@pytest.mark.parametrize(
    "q,intent",
    [
        ("Compare the basic and pro plans", "comparison"),
        ("Where can I find the data retention section?", "navigation"),
        ("How many vacation days do employees get?", "calculation"),
        ("hello", "chitchat"),
        ("What is the refund window?", "lookup"),
    ],
)
def test_intent_classification(q, intent):
    assert analyze_query(q).intent == intent


def test_historical_question_does_not_demand_current():
    a = analyze_query("What was the refund policy in 2022 before the latest change?")
    assert a.wants_historical and not a.wants_current
    assert all(r.kind != "current" for r in a.requirements)


# --- sufficiency ------------------------------------------------------------------


def test_sufficient_when_terms_are_covered():
    a = analyze_query("refund window for annual plans")
    r = evaluate_sufficiency(a, [chunk("Annual plans have a refund window of 30 days.")])
    assert r.sufficient and r.coverage == 1.0 and r.missing == []


def test_insufficient_when_key_terms_missing():
    a = analyze_query("refund window for annual plans")
    r = evaluate_sufficiency(a, [chunk("Our office is closed on public holidays.", 0.4)])
    assert not r.sufficient and r.failure_kind == "insufficient_evidence"
    assert "refund" in r.missing


def test_high_reranker_confidence_overrides_lexical_gap():
    # Synonyms: evidence says "return period"; the reranker is very sure it is relevant.
    a = analyze_query("refund window for annual plans")
    r = evaluate_sufficiency(a, [chunk("The return period for yearly subscriptions is 30 days.", 0.9)])
    assert r.sufficient


def test_plural_stemming_counts_as_coverage():
    a = analyze_query("annual plans")
    assert evaluate_sufficiency(a, [chunk("The annual plan renews automatically.")]).sufficient


def test_current_question_with_only_superseded_evidence_is_outdated():
    a = analyze_query("What is the current refund policy?")
    r = evaluate_sufficiency(a, [chunk("Refund policy: 14 days.", 0.9, is_current=False)])
    assert not r.sufficient and r.failure_kind == "outdated"


def test_policy_question_with_only_drafts_is_insufficient():
    a = analyze_query("What is the refund policy?")
    r = evaluate_sufficiency(a, [chunk("Refund policy draft: 90 days.", 0.9, tier="draft")])
    assert not r.sufficient and "draft" in r.reason.lower()


def test_no_chunks_and_chitchat():
    assert not evaluate_sufficiency(analyze_query("refund policy"), []).sufficient
    assert evaluate_sufficiency(analyze_query("hello"), []).sufficient
