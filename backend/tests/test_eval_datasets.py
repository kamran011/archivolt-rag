from pathlib import Path

import pytest

from app.evals.dataset import load_dataset
from app.evals.metrics import _norm

EVALS = Path(__file__).resolve().parent.parent / "evals"
CORPUS_DATASETS = ["v2.jsonl", "multihop.jsonl"]


def _corpus() -> dict[str, str]:
    docs = {}
    for path in (EVALS / "corpus").glob("*.md"):
        text = path.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip()
        # Same whitespace/case normalization the relevance metric applies to chunks.
        docs[title.lower()] = _norm(text)
    return docs


@pytest.mark.parametrize("path", sorted((EVALS / "datasets").glob("*.jsonl")), ids=lambda p: p.name)
def test_dataset_parses(path):
    assert load_dataset(path)


@pytest.mark.parametrize("name", CORPUS_DATASETS)
def test_gold_ground_truth_exists_in_the_corpus(name):
    corpus = _corpus()
    for case in load_dataset(EVALS / "datasets" / name):
        for title in case.gold_documents:
            assert title.lower() in corpus, f"{case.id}: no corpus document titled {title!r}"
        texts = [corpus[t.lower()] for t in case.gold_documents] or list(corpus.values())
        for passage in case.gold_passages:
            assert any(_norm(passage) in t for t in texts), (
                f"{case.id}: passage {passage!r} not found"
            )
