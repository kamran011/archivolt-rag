"""Jev (TypeSafe) questions, thresholds and the decision table for sufficiency.

Everything a reviewer should audit lives here and nowhere else: the wording of each
question, the thresholds, and the truth table that turns Jev's probabilities into a
decision. Per the TypeSafe guidance, Jev supplies judgments and code makes the decision, so
"is the evidence sufficient?" is never asked directly.

This module is independent of the wire format. The HTTP client that sends these questions
must follow the live TypeSafe API schema (https://docs.typesafe.ai/go/api.md); until it is
wired in, `JevDecisionProvider` keeps using the rules verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# Noul thresholds: above YES reads as true, below NO as false, the band between is "unsettled".
YES_THRESHOLD = 0.7
NO_THRESHOLD = 0.3

# State sent with the questions: named fields, only what a person would look at.
STATE_FIELDS = ("question", "passages")  # passages: [{"title": str, "text": str}]

# One judgment each, phrased so that "true" is the yes answer. Each is a Noul.
Q_ANSWERS = "`passages` state the specific information that `question` asks for."
Q_CONTRADICT = "Two or more `passages` give conflicting answers to `question`."
QUESTIONS = {"answers": Q_ANSWERS, "contradict": Q_CONTRADICT}


class Verdict(str, Enum):
    sufficient = "sufficient"
    insufficient = "insufficient"
    unsettled = "unsettled"  # defer to the rules provider


@dataclass(frozen=True)
class JevAnswers:
    answers: float  # P(Q_ANSWERS is true)
    contradict: float  # P(Q_CONTRADICT is true)


def decide(a: JevAnswers) -> Verdict:
    """Truth table (every combination has an outcome):

    answers >= YES  and contradict <  YES  -> sufficient
    answers >= YES  and contradict >= YES  -> sufficient (conflicts are handled downstream
                                              by the conflict detector/resolver)
    answers <= NO                          -> insufficient
    NO < answers < YES                     -> unsettled (rules decide)
    """
    if a.answers >= YES_THRESHOLD:
        return Verdict.sufficient
    if a.answers <= NO_THRESHOLD:
        return Verdict.insufficient
    return Verdict.unsettled
