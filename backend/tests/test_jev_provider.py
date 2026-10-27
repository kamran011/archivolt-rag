import json
import uuid

import httpx
import pytest

from app.config import settings
from app.domains.retrieval.analyzer import analyze_query
from app.domains.retrieval.decisions import jev_questions as jq
from app.domains.retrieval.decisions.jev_provider import JevDecisionProvider
from app.domains.retrieval.schemas import RetrievedChunk
from app.providers.typesafe import client as typesafe

Q = "What is the refund window for annual subscriptions?"


def chunk(text, title="Refund policy", current=True, tier="standard"):
    cid = uuid.uuid4()
    return RetrievedChunk(
        chunk_id=cid, document_id=cid, document_title=title, content=text, score=0.3,
        metadata={}, retrieval_method="hybrid", is_current=current, authority_tier=tier,
    )


CHUNKS = [chunk("Customers may return annual plans within 30 days of purchase.")]


@pytest.fixture(autouse=True)
def _jev_settings(monkeypatch):
    monkeypatch.setattr(settings, "JEV_API_KEY", "test-key")
    monkeypatch.setattr(settings, "JEV_BASE_URL", "https://api.typesafe.ai")
    monkeypatch.setattr(settings, "JEV_MODEL", "jev-latest")


def jev_returning(p: float, sent: list | None = None):
    def handler(request: httpx.Request):
        if sent is not None:
            sent.append(request)
        return httpx.Response(
            200,
            json={
                "model": "jev-1.14",
                "answers": {jq.STATES_ANSWER: {"type": "noul", "noul": p}},
                "usage": {"input_tokens": 120, "output_tokens": 12},
            },
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_request_matches_system_one_schema():
    sent: list[httpx.Request] = []
    await JevDecisionProvider(jev_returning(0.9, sent)).evaluate_sufficiency(analyze_query(Q), CHUNKS)
    (req,) = sent
    assert str(req.url) == "https://api.typesafe.ai/v1/systemone"
    assert req.headers["Authorization"] == "Bearer test-key"
    body = json.loads(req.content)
    assert set(body) == {"model", "state", "questions"}
    assert body["model"] == "jev-latest"
    assert body["state"] == {
        "question": Q,
        "passages": {"passage_1": {"document": "Refund policy", "text": CHUNKS[0].content}},
    }
    q = body["questions"][jq.STATES_ANSWER]
    assert q["type"] == "noul" and set(q["criteria"]) == {"true", "false"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("p", "expected"),
    [(0.95, True), (0.7, True), (0.05, False), (0.3, False)],
)
async def test_jev_answer_decides(p, expected):
    result = await JevDecisionProvider(jev_returning(p)).evaluate_sufficiency(analyze_query(Q), CHUNKS)
    assert result.sufficient is expected
    assert "Jev" in (result.reason or "")


@pytest.mark.asyncio
async def test_unsettled_band_keeps_rules_verdict():
    analysis = analyze_query(Q)
    rules = await JevDecisionProvider().__dict__["_rules"].evaluate_sufficiency(analysis, CHUNKS)
    result = await JevDecisionProvider(jev_returning(0.5)).evaluate_sufficiency(analysis, CHUNKS)
    assert result == rules


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="boom"),
        httpx.Response(422, json={"detail": [{"loc": ["body", "state"], "msg": "Field required", "type": "missing"}]}),
        httpx.Response(200, json={"model": "jev", "answers": {}, "usage": {}}),
        httpx.Response(200, text="not json"),
    ],
)
async def test_failed_call_is_not_a_no(response):
    """A failed call falls back to the rules verdict instead of becoming 'insufficient'."""
    covered = [chunk("The refund window for annual subscriptions is 30 days.")]
    analysis = analyze_query(Q)
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response))
    result = await JevDecisionProvider(http).evaluate_sufficiency(analysis, covered)
    rules = await JevDecisionProvider().__dict__["_rules"].evaluate_sufficiency(analysis, covered)
    assert result == rules


@pytest.mark.asyncio
async def test_code_decided_cases_never_call_jev(monkeypatch):
    def fail(request):
        raise AssertionError("Jev must not be called")

    http = httpx.AsyncClient(transport=httpx.MockTransport(fail))
    provider = JevDecisionProvider(http)
    outdated = [chunk("Old refund rules.", current=False)]
    assert not (await provider.evaluate_sufficiency(analyze_query("What is the current refund window?"), outdated)).sufficient
    assert (await provider.evaluate_sufficiency(analyze_query("hi"), CHUNKS)).sufficient
    assert not (await provider.evaluate_sufficiency(analyze_query(Q), [])).sufficient
    monkeypatch.setattr(settings, "JEV_API_KEY", "")
    await provider.evaluate_sufficiency(analyze_query(Q), CHUNKS)


def test_decision_table_covers_every_band():
    assert jq.decide(0.9) is jq.Verdict.sufficient
    assert jq.decide(0.1) is jq.Verdict.insufficient
    assert jq.decide(0.5) is jq.Verdict.unsettled


def test_state_caps_passages_and_uses_stable_names():
    many = [chunk("x" * 5000, title=f"Doc {i}") for i in range(12)]
    state = jq.build_state("q", many)
    assert list(state["passages"]) == [f"passage_{i}" for i in range(1, jq.MAX_PASSAGES + 1)]
    assert len(state["passages"]["passage_1"]["text"]) == jq.MAX_PASSAGE_CHARS


@pytest.mark.asyncio
async def test_client_requires_key(monkeypatch):
    monkeypatch.setattr(settings, "JEV_API_KEY", "")
    with pytest.raises(typesafe.TypeSafeError):
        await typesafe.system_one("s", {"q": {"type": "noul", "instructions": "?"}})
