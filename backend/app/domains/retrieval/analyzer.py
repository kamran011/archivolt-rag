"""Query analysis and evidence-requirement planning.

Deterministic on purpose (free, fast, predictable, testable). Turns a question into
(1) coarse intent flags and (2) explicit evidence requirements that the sufficiency gate
checks the retrieved evidence against, instead of trusting a bare top-K score.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

Intent = Literal["lookup", "comparison", "navigation", "calculation", "chitchat", "general"]

_STOPWORDS = frozenset(
    """a an the and or but if then else of to in on at by for with from as is are was were be
    been being do does did done can could should would will shall may might must what which who
    whom whose when where why how this that these those it its i we you they he she them our your
    their my me us about into over under than so such not no any all each per via vs also tell
    give show explain describe please there here have has had get gets""".split()
)
_TEMPORAL_CURRENT = re.compile(
    r"\b(current(ly)?|latest|now|today|presently|up[- ]to[- ]date|newest|at the moment)\b", re.I
)
_TEMPORAL_HISTORICAL = re.compile(
    r"\b(previous(ly)?|formerly|used to|back in|historical(ly)?|as of|in (19|20)\d\d|before)\b",
    re.I,
)
_AUTHORITATIVE = re.compile(
    r"\b(polic(y|ies)|official|contract|agreement|terms|requirement|regulation|standard|"
    r"specification|compliance|sla)\b",
    re.I,
)
_COMPARISON = re.compile(r"\b(compare|versus|vs\.?|difference between|differ|better than)\b", re.I)
_NAVIGATION = re.compile(
    r"\b(where (is|are|can i find)|which (section|page|chapter|document)|find the (section|page))\b",
    re.I,
)
_CALC = re.compile(r"\b(calculate|how much|how many|total|sum of|percentage|average)\b", re.I)
_CHITCHAT = re.compile(r"^\s*(hi|hello|hey|thanks|thank you|good (morning|evening))\b", re.I)


class EvidenceRequirement(BaseModel):
    kind: Literal["term", "current", "authoritative"]
    value: str = ""
    description: str


class QueryAnalysis(BaseModel):
    intent: Intent
    query: str = ""  # the analyzed question, for LLM/Jev decision providers
    terms: list[str] = Field(default_factory=list)
    wants_current: bool = False
    wants_historical: bool = False
    wants_authoritative: bool = False
    requirements: list[EvidenceRequirement] = Field(default_factory=list)


MAX_TERMS = 6


def _key_terms(query: str) -> list[str]:
    seen: list[str] = []
    for tok in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9\-_.]*", query.lower()):
        tok = tok.strip("-_.")
        if len(tok) < 3 or tok in _STOPWORDS or tok in seen:
            continue
        seen.append(tok)
    return seen[:MAX_TERMS]


def analyze_query(query: str) -> QueryAnalysis:
    return _analyze(query).model_copy(update={"query": query})


def _analyze(query: str) -> QueryAnalysis:
    q = query.strip()
    if _CHITCHAT.search(q) and len(q.split()) <= 4:
        return QueryAnalysis(intent="chitchat")

    if _COMPARISON.search(q):
        intent: Intent = "comparison"
    elif _NAVIGATION.search(q):
        intent = "navigation"
    elif _CALC.search(q):
        intent = "calculation"
    elif "?" in q or len(q.split()) >= 3:
        intent = "lookup"
    else:
        intent = "general"

    historical = bool(_TEMPORAL_HISTORICAL.search(q))
    # "current" only matters when the question isn't explicitly about the past.
    current = bool(_TEMPORAL_CURRENT.search(q)) and not historical
    authoritative = bool(_AUTHORITATIVE.search(q))
    terms = _key_terms(q)

    reqs = [
        EvidenceRequirement(kind="term", value=t, description=f"mentions '{t}'") for t in terms
    ]
    if current:
        reqs.append(
            EvidenceRequirement(kind="current", description="comes from the current version")
        )
    if authoritative:
        reqs.append(
            EvidenceRequirement(
                kind="authoritative", description="comes from a non-draft source"
            )
        )
    return QueryAnalysis(
        intent=intent,
        terms=terms,
        wants_current=current,
        wants_historical=historical,
        wants_authoritative=authoritative,
        requirements=reqs,
    )
