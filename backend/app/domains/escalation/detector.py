"""Should this turn be handed to a human? Judgments in, decision in code.

Signals:
- abstain: the answer abstained (reuses the evidence gate / sufficiency decision as is)
- user_request: the user asks for a person
- frustration: the user sounds frustrated

user_request and frustration are judged by Jev (TypeSafe) when it is configured, one Noul per
signal in a single request; the questions and thresholds live in this module. Rules cover the
case where Jev is not configured, fails, or is unsure (between the thresholds), so the
decision never depends on Jev being up.
"""

from __future__ import annotations

import re

import structlog

from app.config import settings
from app.domains.escalation.settings import EscalationSettings
from app.providers.typesafe import client as typesafe

logger = structlog.get_logger()

YES_THRESHOLD = 0.7
NO_THRESHOLD = 0.3
MAX_MESSAGE_CHARS = 1500
EARLIER_USER_MESSAGES = 3

ASKS_FOR_HUMAN = "asks_for_human"
FRUSTRATED = "frustrated"
JEV_QUESTIONS: dict[str, dict] = {
    ASKS_FOR_HUMAN: {
        "type": "noul",
        "instructions": "Does `latest_message` ask to talk to a human instead of the assistant?",
        "criteria": {
            "true": "The customer asks for a person, agent, representative or staff member to "
            "help them, or to be contacted by one.",
            "false": "The customer asks a question the assistant could answer, even if it "
            "mentions staff, support or people in passing.",
        },
    },
    FRUSTRATED: {
        "type": "noul",
        "instructions": "Does the customer sound frustrated in `latest_message`?",
        "criteria": {
            "true": "The message shows annoyance or exasperation, for example complaining that "
            "the answers are wrong, useless or keep missing the point.",
            "false": "The message is neutral or polite, including a calm repeat of a question.",
        },
    },
}

_ASK_HUMAN_RE = re.compile(
    r"\b(talk|speak|chat)\s+(to|with)\s+(a|an|some|the)?\s*"
    r"(human|person|someone|somebody|agent|representative|rep|staff|manager|real person)\b"
    r"|\b(human|live|real)\s+(agent|person|support|representative)\b"
    r"|\b(connect|transfer)\s+me\s+(to|with)\b"
    r"|\bcontact\s+(support|a human|someone)\b",
    re.I,
)
_FRUSTRATION_RE = re.compile(
    r"\b(useless|ridiculous|terrible|awful|frustrat\w*|annoy\w*|angry|stupid|wtf|"
    r"waste of (my )?time|not helpful|unhelpful|doesn'?t help|still (not|doesn'?t|isn'?t)|"
    r"you('re| are) (wrong|not listening))\b|!{3,}|\?{3,}",
    re.I,
)


def rule_asks_for_human(message: str) -> bool:
    return bool(_ASK_HUMAN_RE.search(message))


def rule_frustrated(message: str) -> bool:
    if _FRUSTRATION_RE.search(message):
        return True
    letters = [c for c in message if c.isalpha()]
    return len(letters) >= 12 and sum(c.isupper() for c in letters) / len(letters) > 0.7


def _decide(p: float | None, rule: bool) -> bool:
    """Truth table: Jev yes (>= YES) -> yes; Jev no (<= NO) -> no; unsure or no Jev -> rule."""
    if p is None or NO_THRESHOLD < p < YES_THRESHOLD:
        return rule
    return p >= YES_THRESHOLD


async def _jev_judgments(message: str, earlier: list[str], wanted: list[str]) -> dict[str, float]:
    if not wanted or not settings.ESCALATION_USE_JEV or not typesafe.configured():
        return {}
    state = {
        "latest_message": message[:MAX_MESSAGE_CHARS],
        "earlier_user_messages": [m[:MAX_MESSAGE_CHARS] for m in earlier[-EARLIER_USER_MESSAGES:]],
    }
    try:
        response = await typesafe.system_one(state, {k: JEV_QUESTIONS[k] for k in wanted})
        return {k: response.noul(k) for k in wanted}
    except typesafe.TypeSafeError as e:  # a failed call is not a "no": fall back to rules
        logger.warning("escalation_jev_failed", error=str(e))
        return {}


async def detect_reasons(
    message: str,
    earlier_user_messages: list[str],
    abstained: bool,
    rules: EscalationSettings,
) -> list[str]:
    """Which enabled triggers fire for this turn (empty when none or handoff is disabled)."""
    if not rules.enabled:
        return []
    wanted = []
    if "user_request" in rules.triggers:
        wanted.append(ASKS_FOR_HUMAN)
    if "frustration" in rules.triggers:
        wanted.append(FRUSTRATED)
    judged = await _jev_judgments(message, earlier_user_messages, wanted)

    reasons: list[str] = []
    if "user_request" in rules.triggers and _decide(
        judged.get(ASKS_FOR_HUMAN), rule_asks_for_human(message)
    ):
        reasons.append("user_request")
    if "frustration" in rules.triggers and _decide(
        judged.get(FRUSTRATED), rule_frustrated(message)
    ):
        reasons.append("frustration")
    if "abstain" in rules.triggers and abstained:
        reasons.append("abstain")
    if reasons or judged:
        logger.info("escalation_check", reasons=reasons,
                    jev={k: round(v, 3) for k, v in judged.items()})
    return reasons
