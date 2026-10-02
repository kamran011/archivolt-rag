import json
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, model_validator


class EvalCase(BaseModel):
    id: str
    question: str
    gold_documents: list[str] = Field(default_factory=list)
    """Titles of documents that contain the answer (matched case-insensitively)."""
    gold_passages: list[str] = Field(default_factory=list)
    """Short verbatim snippets that a relevant chunk must contain."""
    expected_keywords: list[str] = Field(default_factory=list)
    """Terms a correct answer should mention."""
    should_abstain: bool = False
    """True for questions the knowledge base cannot answer."""
    tags: list[str] = Field(default_factory=list)
    forbidden_documents: list[str] = Field(default_factory=list)
    """Titles the evaluated caller must NOT see: any citation or mention is a leak."""
    canary: str | None = None
    """A marker planted in a malicious document; it must never appear in the answer."""

    @model_validator(mode="after")
    def _has_ground_truth(self) -> "EvalCase":
        if not self.should_abstain and not (self.gold_documents or self.gold_passages):
            raise ValueError(
                "answerable cases need gold_documents or gold_passages "
                "(otherwise retrieval quality cannot be measured)"
            )
        return self


def parse_dataset(text: str, source: str = "dataset") -> list[EvalCase]:
    """Parses JSONL; blank lines and '#' comment lines are ignored."""
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            case = EvalCase.model_validate(json.loads(line))
        except (json.JSONDecodeError, ValidationError) as e:
            raise ValueError(f"{source}:{lineno}: invalid eval case: {e}") from e
        if case.id in seen:
            raise ValueError(f"{source}:{lineno}: duplicate case id {case.id!r}")
        seen.add(case.id)
        cases.append(case)
    if not cases:
        raise ValueError(f"{source}: dataset is empty")
    return cases


def load_dataset(path: str | Path) -> list[EvalCase]:
    return parse_dataset(Path(path).read_text(encoding="utf-8"), str(path))
