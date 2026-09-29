from statistics import mean
from typing import Any

from pydantic import BaseModel, Field

# Metric name -> direction. "higher": a drop is a regression. "lower": a rise is.
METRIC_DIRECTIONS: dict[str, str] = {
    "hit_rate": "higher",
    "recall": "higher",
    "precision": "higher",
    "mrr": "higher",
    "ndcg": "higher",
    "abstention_accuracy": "higher",
    "false_answer_rate": "lower",  # answered a question that should have been abstained
    "false_abstain_rate": "lower",  # abstained on an answerable question
    "keyword_coverage": "higher",
    "faithfulness": "higher",
    "avg_latency_ms": "lower",
    "avg_cost_usd": "lower",
}


class CaseResult(BaseModel):
    case_id: str
    tags: list[str] = Field(default_factory=list)
    metrics: dict[str, float | None]
    error: str | None = None


class EvalReport(BaseModel):
    dataset: str
    config: dict[str, Any]
    k: int
    total_cases: int
    failed_cases: int
    summary: dict[str, float | None]
    cases: list[CaseResult]


def _avg(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return round(mean(present), 4) if present else None


def summarize(results: list[CaseResult], should_abstain: dict[str, bool]) -> dict[str, float | None]:
    """Aggregates per-case metrics. Retrieval metrics only average answerable
    cases (an unanswerable question has no gold passage to find)."""
    ok = [r for r in results if r.error is None]
    answerable = [r for r in ok if not should_abstain[r.case_id]]
    unanswerable = [r for r in ok if should_abstain[r.case_id]]

    def col(rows: list[CaseResult], name: str) -> float | None:
        return _avg([r.metrics.get(name) for r in rows])

    summary: dict[str, float | None] = {
        name: col(answerable, name)
        for name in ("hit_rate", "recall", "precision", "mrr", "ndcg", "keyword_coverage")
    }
    summary["faithfulness"] = col(answerable, "faithfulness")
    summary["abstention_accuracy"] = col(ok, "abstention_correct")
    summary["false_answer_rate"] = (
        _avg([0.0 if r.metrics.get("abstention_correct") else 1.0 for r in unanswerable])
        if unanswerable
        else None
    )
    summary["false_abstain_rate"] = (
        _avg([0.0 if r.metrics.get("abstention_correct") else 1.0 for r in answerable])
        if answerable
        else None
    )
    summary["avg_latency_ms"] = col(ok, "latency_ms")
    summary["avg_cost_usd"] = col(ok, "cost_usd")
    return summary


class MetricDelta(BaseModel):
    metric: str
    baseline: float
    candidate: float
    delta: float
    regressed: bool


def compare(
    baseline: dict[str, float | None],
    candidate: dict[str, float | None],
    *,
    quality_tolerance: float = 0.02,
    cost_tolerance: float = 0.10,
) -> list[MetricDelta]:
    """Flags regressions. Quality metrics may move by `quality_tolerance`
    (absolute); latency/cost by `cost_tolerance` (relative)."""
    deltas: list[MetricDelta] = []
    for name, direction in METRIC_DIRECTIONS.items():
        base, cand = baseline.get(name), candidate.get(name)
        if base is None or cand is None:
            continue
        delta = cand - base
        if name in ("avg_latency_ms", "avg_cost_usd"):
            regressed = base > 0 and delta / base > cost_tolerance
        elif direction == "higher":
            regressed = delta < -quality_tolerance
        else:
            regressed = delta > quality_tolerance
        deltas.append(
            MetricDelta(
                metric=name,
                baseline=base,
                candidate=cand,
                delta=round(delta, 4),
                regressed=regressed,
            )
        )
    return deltas
