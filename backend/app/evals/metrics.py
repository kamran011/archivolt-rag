"""Pure metric functions (no I/O) so they are cheap to test exhaustively."""

import math
import re

from app.domains.retrieval.schemas import RetrievedChunk
from app.evals.dataset import EvalCase

_WS_RE = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().lower()


def is_relevant(chunk: RetrievedChunk, case: EvalCase) -> bool:
    title = _norm(chunk.document_title)
    if any(_norm(g) == title for g in case.gold_documents):
        return True
    content = _norm(chunk.content)
    return any(_norm(p) in content for p in case.gold_passages)


def _relevance_flags(chunks: list[RetrievedChunk], case: EvalCase, k: int) -> list[bool]:
    return [is_relevant(c, case) for c in chunks[:k]]


def hit_at_k(chunks: list[RetrievedChunk], case: EvalCase, k: int) -> float:
    return 1.0 if any(_relevance_flags(chunks, case, k)) else 0.0


def precision_at_k(chunks: list[RetrievedChunk], case: EvalCase, k: int) -> float:
    flags = _relevance_flags(chunks, case, k)
    return sum(flags) / len(flags) if flags else 0.0


def recall_at_k(chunks: list[RetrievedChunk], case: EvalCase, k: int) -> float:
    """Fraction of the gold targets (documents + passages) covered in the top k."""
    targets = [("doc", _norm(g)) for g in case.gold_documents] + [
        ("passage", _norm(p)) for p in case.gold_passages
    ]
    if not targets:
        return 0.0
    top = chunks[:k]
    titles = {_norm(c.document_title) for c in top}
    contents = [_norm(c.content) for c in top]
    covered = sum(
        1
        for kind, value in targets
        if (kind == "doc" and value in titles)
        or (kind == "passage" and any(value in c for c in contents))
    )
    return covered / len(targets)


def reciprocal_rank(chunks: list[RetrievedChunk], case: EvalCase) -> float:
    for rank, chunk in enumerate(chunks, start=1):
        if is_relevant(chunk, case):
            return 1.0 / rank
    return 0.0


def ndcg_at_k(chunks: list[RetrievedChunk], case: EvalCase, k: int) -> float:
    flags = _relevance_flags(chunks, case, k)
    dcg = sum(1.0 / math.log2(i + 2) for i, rel in enumerate(flags) if rel)
    ideal_hits = min(len(case.gold_documents) + len(case.gold_passages), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    return dcg / idcg if idcg else 0.0


def keyword_coverage(answer: str, expected_keywords: list[str]) -> float | None:
    if not expected_keywords:
        return None
    text = _norm(answer)
    return sum(1 for kw in expected_keywords if _norm(kw) in text) / len(expected_keywords)


def faithfulness(claim_verifications: list) -> float | None:
    """Share of the answer's claims that the verifier found supported."""
    if not claim_verifications:
        return None
    return sum(1 for c in claim_verifications if c.supported) / len(claim_verifications)
