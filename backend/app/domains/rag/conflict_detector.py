import json

import structlog
from pydantic import BaseModel

from app.domains.retrieval.evidence import ContextAssembler
from app.domains.retrieval.schemas import RetrievedChunk
from app.providers.llm.base import LLMProvider

logger = structlog.get_logger()

CONFLICT_DETECTION_PROMPT = """You are checking whether multiple evidence sources contradict \
each other on the same factual point. Given the numbered sources below, identify any pairs of \
sources that make conflicting claims about the same topic (e.g. different numbers, dates, or \
policies for the same thing). Do not flag sources that simply cover different topics.

Sources:
{sources}

Respond with ONLY a JSON array (empty if no conflicts): \
[{{"source_a": 1, "source_b": 2, "topic": "refund window", "claim_a": "...", "claim_b": "..."}}]
No other text."""


class DetectedConflict(BaseModel):
    source_a: int
    source_b: int
    topic: str
    claim_a: str
    claim_b: str


class ConflictDetector:
    async def detect(
        self,
        chunks: list[RetrievedChunk],
        llm: LLMProvider,
    ) -> list[DetectedConflict]:
        distinct_documents = {c.document_id for c in chunks}
        if len(distinct_documents) < 2:
            # A single document can't semantically conflict with itself in a
            # way this check is meant to catch — skip the LLM call entirely.
            return []

        sources_text = ContextAssembler.format_with_citations(chunks)
        prompt = CONFLICT_DETECTION_PROMPT.format(sources=sources_text)

        try:
            response = await llm.generate(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=768,
            )
        except Exception as e:
            logger.warning("conflict_detection_failed", error=str(e))
            return []

        return self._parse_conflicts(response.content)

    def _parse_conflicts(self, raw: str) -> list[DetectedConflict]:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                data = next(iter(data.values())) if data else []
            return [DetectedConflict(**item) for item in data]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.warning("conflict_detection_parse_failed", error=str(e), raw=raw[:200])
            return []


conflict_detector = ConflictDetector()
