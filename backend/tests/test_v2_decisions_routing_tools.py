import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import settings
from app.domains.retrieval.analyzer import analyze_query
from app.domains.retrieval.decisions.llm_provider import LLMDecisionProvider
from app.domains.retrieval.decisions.registry import get_decision_provider
from app.domains.retrieval.schemas import RetrievedChunk
from app.domains.tools import external_api
from app.domains.tools.external_api import ExternalApiTool
from app.providers.llm.base import LLMResponse
from app.providers.llm.model_router import choose_model


def chunk(text, score=0.3):
    cid = uuid.uuid4()
    return RetrievedChunk(
        chunk_id=cid, document_id=cid, document_title="t", content=text, score=score,
        metadata={}, retrieval_method="hybrid",
    )


class FakeLLM:
    def __init__(self, content=None, error=None):
        self.content, self.error = content, error

    async def generate(self, messages, temperature=0.1, max_tokens=2048):
        if self.error:
            raise self.error
        return LLMResponse(content=self.content, prompt_tokens=1, completion_tokens=1,
                           model="f", finish_reason="stop")


Q = "What is the refund window for annual subscriptions?"
CHUNKS = [chunk("Customers may return annual plans within 30 days of purchase.")]


def test_registry_resolves_all_providers():
    assert type(get_decision_provider("llm")).__name__ == "LLMDecisionProvider"
    assert type(get_decision_provider("jev")).__name__ == "JevDecisionProvider"
    with pytest.raises(ValueError):
        get_decision_provider("nope")


@pytest.mark.asyncio
async def test_llm_provider_rescues_synonym_miss_and_falls_back():
    analysis = analyze_query(Q)
    rescue = LLMDecisionProvider(FakeLLM('{"sufficient": true, "missing": [], "reason": "ok"}'))
    assert (await rescue.evaluate_sufficiency(analysis, CHUNKS)).sufficient
    refuse = LLMDecisionProvider(FakeLLM('{"sufficient": false, "missing": ["window"]}'))
    assert not (await refuse.evaluate_sufficiency(analysis, CHUNKS)).sufficient
    broken = LLMDecisionProvider(FakeLLM(error=RuntimeError("x")))
    assert not (await broken.evaluate_sufficiency(analysis, CHUNKS)).sufficient
    garbage = LLMDecisionProvider(FakeLLM("not json"))
    assert not (await garbage.evaluate_sufficiency(analysis, CHUNKS)).sufficient


@pytest.mark.asyncio
async def test_llm_provider_never_stricter_than_rules():
    analysis = analyze_query("refund window")
    covered = [chunk("The refund window is 30 days.", 0.9)]
    llm = MagicMock()
    llm.generate = AsyncMock()
    assert (await LLMDecisionProvider(llm).evaluate_sufficiency(analysis, covered)).sufficient
    llm.generate.assert_not_called()


def test_model_router(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_COST_AWARE_ROUTING", True)
    monkeypatch.setattr(settings, "CHEAP_LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setattr(settings, "DEFAULT_LLM_MODEL", "gpt-4o")
    simple = choose_model("gpt-4o", intent="lookup", query="what is the sla", context_tokens=500)
    assert simple.routed and simple.model == "gpt-4o-mini"
    assert not choose_model("gpt-4o", intent="comparison", query="a vs b", context_tokens=500).routed
    assert not choose_model("gpt-4o", intent="lookup", query="q", context_tokens=9000).routed
    assert not choose_model("claude-x", intent="lookup", query="q", context_tokens=10).routed
    assert not choose_model("gpt-4o", intent="lookup", query="a; b", context_tokens=10).routed
    monkeypatch.setattr(settings, "ENABLE_COST_AWARE_ROUTING", False)
    assert not choose_model("gpt-4o", intent="lookup", query="q", context_tokens=10).routed


def _ctx(enabled=True):
    ctx = MagicMock()
    ctx.org_settings = {"external_api_enabled": enabled}
    ctx.internal_texts = ["the secret internal handbook text is quite long here yes indeed"]
    return ctx


SOURCES = '{"orders": {"url": "https://api.example.com/orders", "description": "orders"}, "bad": {"url": "http://x.com"}}'


def test_external_api_allowlist_and_gating(monkeypatch):
    monkeypatch.setattr(settings, "EXTERNAL_API_SOURCES", SOURCES)
    assert list(external_api.load_sources()) == ["orders"]  # http source rejected
    tool = ExternalApiTool()
    assert tool.denied_reason(_ctx()) is None
    assert tool.denied_reason(_ctx(enabled=False))
    monkeypatch.setattr(settings, "EXTERNAL_API_SOURCES", "")
    assert tool.denied_reason(_ctx())


@pytest.mark.asyncio
async def test_external_api_run_labels_result_and_blocks_leaks(monkeypatch):
    monkeypatch.setattr(settings, "EXTERNAL_API_SOURCES", SOURCES)
    seen = {}

    async def fake_fetch(url, params, headers):
        seen.update(url=url, params=params)
        return {"id": 7, "status": "shipped"}

    monkeypatch.setattr(external_api, "fetch_json", fake_fetch)
    tool = ExternalApiTool()
    ok = await tool.run(_ctx(), tool.Args(source="orders", params={"id": 7}))
    assert ok.ok and seen == {"url": "https://api.example.com/orders", "params": {"id": "7"}}
    assert ok.chunks[0].metadata["source"] == "external" and "shipped" in ok.chunks[0].content

    unknown = await tool.run(_ctx(), tool.Args(source="https://evil.example"))
    assert not unknown.ok
    leak = await tool.run(_ctx(), tool.Args(source="orders", params={"q": "a@b.com"}))
    assert not leak.ok and "blocked" in leak.error
