import pytest

from app.domains.retrieval.query_transform import QueryPlan, parse_plan, plan_queries
from app.providers.llm.base import LLMResponse


class FakeLLM:
    def __init__(self, content=None, error=None):
        self.content, self.error = content, error

    async def generate(self, messages, temperature=0.1, max_tokens=2048):
        if self.error:
            raise self.error
        return LLMResponse(
            content=self.content,
            prompt_tokens=10,
            completion_tokens=5,
            model="fake",
            finish_reason="stop",
        )


def test_parse_plan_extracts_fields_from_noisy_output():
    raw = 'Sure!\n```json\n{"rewrite": "refund policy for annual plans", "sub_queries": ["a", "b"], "variants": ["c", "d"]}\n```'
    plan = parse_plan("what about annual?", raw, max_extra=3)
    assert plan.primary == "refund policy for annual plans"
    assert plan.sub_queries == ["a", "b"]
    assert plan.variants == ["c"]  # budget of 3 extras shared, sub-queries first


def test_parse_plan_bad_output_falls_back_to_original():
    for raw in ["no json here", "{not json}", "[1, 2]", '{"rewrite": 5, "sub_queries": "x"}']:
        plan = parse_plan("q", raw, max_extra=3)
        assert plan.primary == "q"
        assert plan.extra_queries == []


def test_extra_queries_dedup_against_primary_and_each_other():
    plan = QueryPlan(
        original="Refund policy",
        rewrite="refund  policy",
        sub_queries=["Shipping policy", "shipping policy"],
        variants=["REFUND POLICY", "returns"],
    )
    assert plan.extra_queries == ["Shipping policy", "returns"]


@pytest.mark.asyncio
async def test_plan_queries_success_and_token_accounting():
    llm = FakeLLM('{"rewrite": "x y", "sub_queries": [], "variants": ["z"]}')
    plan = await plan_queries("it?", llm, [{"role": "user", "content": "x"}])
    assert plan.primary == "x y"
    assert plan.extra_queries == ["z"]
    assert (plan.prompt_tokens, plan.completion_tokens) == (10, 5)


@pytest.mark.asyncio
async def test_plan_queries_provider_error_degrades_to_original():
    plan = await plan_queries("original q", FakeLLM(error=RuntimeError("boom")))
    assert plan.primary == "original q"
    assert plan.extra_queries == []
