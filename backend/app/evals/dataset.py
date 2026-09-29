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

    @model_validator(mode="after")
    def _has_ground_truth(self) -> "EvalCase":
        if not self.should_abstain and not (self.gold_documents or self.gold_passages):
            raise ValueError(
                "answerable cases need gold_documents or gold_passages "
                "(otherwise retrieval quality cannot be measured)"
            )
        return self


def load_dataset(path: str | Path) -> list[EvalCase]:
    """Loads a JSONL dataset; blank lines and '#' comment lines are ignored."""
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for lineno, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            case = EvalCase.model_validate(json.loads(line))
        except (json.JSONDecodeError, ValidationError) as e:
            raise ValueError(f"{path}:{lineno}: invalid eval case: {e}") from e
        if case.id in seen:
            raise ValueError(f"{path}:{lineno}: duplicate case id {case.id!r}")
        seen.add(case.id)
        cases.append(case)
    if not cases:
        raise ValueError(f"{path}: dataset is empty")
    return cases
