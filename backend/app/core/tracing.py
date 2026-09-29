"""
Lightweight retrieval tracing.

Records named spans (start time, duration, metadata) for each stage of a
RAG request.  Spans are accumulated on a `RetrievalTrace` object and emitted
as a single structured log event when the trace is finalised.  The shape
matches OTel span attributes so the logs can be forwarded to an OTel
collector later without changing the call sites.

Usage:
    trace = RetrievalTrace(query="...", org_id=org_id)
    with trace.span("retrieval"):
        ...
    with trace.span("rerank", candidates=20):
        ...
    trace.finish(answer_tokens=128)
    # → emits a structlog event with all spans + summary metadata
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class Span:
    name: str
    start_time: float
    end_time: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float | None:
        if self.end_time is None:
            return None
        return round((self.end_time - self.start_time) * 1000, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "duration_ms": self.duration_ms,
            **self.attributes,
        }


class RetrievalTrace:
    """Accumulates timing spans for one RAG request and emits them as a log."""

    def __init__(self, query: str, org_id: uuid.UUID) -> None:
        self.trace_id = str(uuid.uuid4())
        self.query_preview = query[:120]
        self.org_id = str(org_id)
        self.start_time = time.perf_counter()
        self._spans: list[Span] = []

    @contextmanager
    def span(self, name: str, **attributes: Any):
        """Context manager that records a named span."""
        s = Span(name=name, start_time=time.perf_counter(), attributes=attributes)
        try:
            yield s
        finally:
            s.end_time = time.perf_counter()
            self._spans.append(s)

    def finish(self, **summary_attributes: Any) -> dict[str, Any]:
        """
        Emit a structured log event with all spans and return the trace dict.
        Call once after all spans have been recorded.
        """
        total_ms = round((time.perf_counter() - self.start_time) * 1000, 2)
        trace = {
            "trace_id": self.trace_id,
            "org_id": self.org_id,
            "query_preview": self.query_preview,
            "total_ms": total_ms,
            "spans": [s.to_dict() for s in self._spans],
            **summary_attributes,
        }
        logger.info("rag_trace", **trace)
        return trace

    def to_spans_dict(self) -> dict[str, float | None]:
        """Return {span_name: duration_ms} for embedding in retrieval_metadata."""
        return {s.name: s.duration_ms for s in self._spans}
