"""Jev (TypeSafe) questions, thresholds and the decision table for evidence sufficiency.

Everything a reviewer should audit lives here and nowhere else: the state Jev sees, the
wording of each question, the thresholds, and the truth table that turns Jev's answers
into a decision. Per the TypeSafe guidance, Jev supplies judgments and code makes the
decision, so "is the evidence sufficient?" is never asked directly.
"""

from __future__ import annotations

from enum import Enum

from app.domains.retrieval.schemas import RetrievedChunk

# TypeSafe's suggested starting thresholds for a Noul: above YES reads as yes, below NO as
# no, and the band between means the state does not settle the question.
YES_THRESHOLD = 0.7
NO_THRESHOLD = 0.3

MAX_PASSAGES = 8
MAX_PASSAGE_CHARS = 1500

# The one judgment the decision depends on. Instructions are phrased so "true" means yes;
# the criteria name the case that causes confusion (on-topic but missing the fact).
STATES_ANSWER = "states_answer"
QUESTIONS: dict[str, dict] = {
    STATES_ANSWER: {
        "type": "noul",
        "instructions": "Do the `passages` state the information that `question` asks for?",
        "criteria": {
            "true": "At least one passage states the specific fact, figure, rule or "
            "procedure the question asks about.",
            "false": "The passages discuss the same topic but never state what the question "
            "asks about, or they are about something else.",
        },
    },
}


def build_state(question: str, chunks: list[RetrievedChunk]) -> dict:
    """What a person would look at: the question and the selected passages, each with the
    title of the document it came from. Passages get stable names, not list positions."""
    return {
        "question": question,
        "passages": {
            f"passage_{i}": {"document": c.document_title, "text": c.content[:MAX_PASSAGE_CHARS]}
            for i, c in enumerate(chunks[:MAX_PASSAGES], start=1)
        },
    }


class Verdict(str, Enum):
    sufficient = "sufficient"
    insufficient = "insufficient"
    unsettled = "unsettled"  # the rules provider decides


def decide(states_answer: float) -> Verdict:
    """Truth table (every value has an outcome):

    states_answer >= YES_THRESHOLD       -> sufficient
    states_answer <= NO_THRESHOLD        -> insufficient
    NO_THRESHOLD < states_answer < YES   -> unsettled: keep the rules verdict
    Freshness and authority are decided in code (rules) before Jev is asked.
    """
    if states_answer >= YES_THRESHOLD:
        return Verdict.sufficient
    if states_answer <= NO_THRESHOLD:
        return Verdict.insufficient
    return Verdict.unsettled
