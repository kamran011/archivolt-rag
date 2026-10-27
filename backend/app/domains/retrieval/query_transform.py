"""Query rewriting, multi-query and sub-query decomposition (V2 adaptive retrieval).

One bounded LLM call turns the user's question into a retrieval plan:
- rewrite: a standalone version (pronouns/ellipsis resolved from the conversation)
- sub_queries: independent parts of a multi-part or comparison question
- variants: alternative phrasings of the same question (multi-query)

Any failure (provider error, bad JSON, empty output) degrades to the original query, so
this can only add recall, never break retrieval. Extra queries are searched with the same
org/KB scope as the original; this module never touches access control.
"""

from __future__ import annotations

import json
import re

import structlog
from pydantic import BaseModel, Field

from app.providers.llm.base import LLMProvider

logger = structlog.get_logger()

MAX_QUERY_CHARS = 300
MAX_HISTORY_TURNS = 4

QUERY_PLAN_PROMPT = """You prepare search queries for a document retrieval system.
Given a user question (and optional conversation), return ONLY a JSON object:
{{"rewrite": "...", "sub_queries": ["..."], "variants": ["..."]}}

- rewrite: the question as a self-contained search query. Resolve pronouns and references
  using the conversation. Keep it unchanged if it is already standalone.
- sub_queries: only if the question has several independent parts or compares things,
  one self-contained query per part. Otherwise [].
- variants: at most 2 alternative phrasings using different keywords. Otherwise [].
Never answer the question. Never add facts that are not in the question or conversation.

Conversation:
{history}

Question: {question}"""


class QueryPlan(BaseModel):
    original: str
    rewrite: str | None = None
    sub_queries: list[str] = Field(default_factory=list)
    variants: list[str] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def primary(self) -> str:
        """The query to search/rerank with."""
        return self.rewrite or self.original

    @property
    def extra_queries(self) -> list[str]:
        """Additional queries to search, de-duplicated against the primary and each other."""
        seen = {_norm(self.primary), _norm(self.original)}
        out: list[str] = []
        for q in [*self.sub_queries, *self.variants]:
            if _norm(q) not in seen:
                seen.add(_norm(q))
                out.append(q)
        return out


def _norm(q: str) -> str:
    return " ".join(q.lower().split())


def _clean(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text[:MAX_QUERY_CHARS] if text else None


def _format_history(history: list[dict] | None) -> str:
    if not history:
        return "(none)"
    turns = history[-MAX_HISTORY_TURNS:]
    return "\n".join(
        f"{t.get('role', 'user')}: {str(t.get('content', ''))[:MAX_QUERY_CHARS]}" for t in turns
    )


def parse_plan(original: str, raw: str, max_extra: int) -> QueryPlan:
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return QueryPlan(original=original)
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return QueryPlan(original=original)
    if not isinstance(data, dict):
        return QueryPlan(original=original)

    def clean_list(key: str) -> list[str]:
        items = data.get(key)
        if not isinstance(items, list):
            return []
        return [c for c in (_clean(i) for i in items) if c]

    plan = QueryPlan(
        original=original,
        rewrite=_clean(data.get("rewrite")),
        sub_queries=clean_list("sub_queries"),
        variants=clean_list("variants"),
    )
    # Sub-queries are the more valuable extras; variants fill what budget is left.
    budget = max(0, max_extra)
    plan.sub_queries = plan.sub_queries[:budget]
    plan.variants = plan.variants[: max(0, budget - len(plan.sub_queries))]
    return plan


async def plan_queries(
    query: str,
    llm: LLMProvider,
    history: list[dict] | None = None,
    max_extra: int = 3,
) -> QueryPlan:
    try:
        response = await llm.generate(
            messages=[
                {
                    "role": "user",
                    "content": QUERY_PLAN_PROMPT.format(
                        history=_format_history(history), question=query
                    ),
                }
            ],
            temperature=0.0,
            max_tokens=400,
        )
    except Exception as e:
        logger.warning("query_transform_failed", error=str(e))
        return QueryPlan(original=query)
    plan = parse_plan(query, response.content, max_extra)
    plan.prompt_tokens = response.prompt_tokens
    plan.completion_tokens = response.completion_tokens
    return plan
