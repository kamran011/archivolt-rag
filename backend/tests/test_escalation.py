"""Human handoff: settings validation, detection (rules + Jev), notification content."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.domains.escalation import detector, notify
from app.domains.escalation.settings import EscalationSettings, load_settings
from app.providers.typesafe.client import SystemOneResponse, TypeSafeError

ON = EscalationSettings(enabled=True)


def test_slack_webhook_must_be_slack():
    EscalationSettings(slack_webhook_url="https://hooks.slack.com/services/T0/B0/x")
    with pytest.raises(ValidationError):
        EscalationSettings(slack_webhook_url="https://evil.example/collect")


def test_invalid_stored_settings_disable_handoff():
    bad = {"escalation": {"enabled": True, "slack_webhook_url": "http://169.254.169.254/"}}
    assert load_settings(bad).enabled is False
    assert load_settings({}).enabled is False
    ok = load_settings({"escalation": {"enabled": True, "emails": ["team@acme.com"]}})
    assert ok.enabled and ok.triggers == ["user_request", "frustration", "abstain"]


@pytest.mark.parametrize("msg", [
    "Can I talk to a human please?", "I want to speak with a real person",
    "connect me to an agent", "is there live support?",
])
def test_rule_asks_for_human(msg):
    assert detector.rule_asks_for_human(msg)


@pytest.mark.parametrize("msg", [
    "What are your support hours?", "How do I contact the manager of my account settings page?",
    "Who is the person responsible for refunds in the policy?",
])
def test_rule_does_not_flag_ordinary_questions(msg):
    assert not detector.rule_asks_for_human(msg)


@pytest.mark.parametrize("msg,frustrated", [
    ("This is useless, you keep giving me the wrong answer", True),
    ("WHY IS MY ORDER STILL NOT HERE", True),
    ("Seriously???", True),
    ("Thanks, that helps. What about shipping to Spain?", False),
])
def test_rule_frustrated(msg, frustrated):
    assert detector.rule_frustrated(msg) is frustrated


@pytest.fixture
def no_jev(monkeypatch):
    monkeypatch.setattr(detector.typesafe, "configured", lambda: False)


async def test_disabled_never_escalates(no_jev):
    assert await detector.detect_reasons("talk to a human!!!", [], True, EscalationSettings()) == []


async def test_rules_and_abstain_without_jev(no_jev):
    assert await detector.detect_reasons("talk to a human", [], False, ON) == ["user_request"]
    assert await detector.detect_reasons("What is E-14?", [], True, ON) == ["abstain"]
    only_abstain = EscalationSettings(enabled=True, triggers=["abstain"])
    assert await detector.detect_reasons("talk to a human", [], False, only_abstain) == []


def _jev(asks: float, frustrated: float):
    return SystemOneResponse(model="jev-1.14.0", usage={}, answers={
        detector.ASKS_FOR_HUMAN: {"type": "noul", "noul": asks},
        detector.FRUSTRATED: {"type": "noul", "noul": frustrated},
    })


async def test_jev_overrides_rules_when_confident(monkeypatch):
    monkeypatch.setattr(detector.typesafe, "configured", lambda: True)
    # Jev catches what the rules miss ...
    with patch.object(detector.typesafe, "system_one", AsyncMock(return_value=_jev(0.95, 0.9))):
        r = await detector.detect_reasons("Can somebody from your team call me back?", [], False, ON)
    assert r == ["user_request", "frustration"]
    # ... and clears a rule false positive.
    with patch.object(detector.typesafe, "system_one", AsyncMock(return_value=_jev(0.05, 0.1))):
        assert await detector.detect_reasons("talk to a human???", [], False, ON) == []


async def test_jev_unsure_or_failing_falls_back_to_rules(monkeypatch):
    monkeypatch.setattr(detector.typesafe, "configured", lambda: True)
    with patch.object(detector.typesafe, "system_one", AsyncMock(return_value=_jev(0.5, 0.5))):
        assert await detector.detect_reasons("talk to a human", [], False, ON) == ["user_request"]
    with patch.object(detector.typesafe, "system_one", AsyncMock(side_effect=TypeSafeError("x"))):
        assert await detector.detect_reasons("talk to a human", [], False, ON) == ["user_request"]


def _msg(role, content, **kw):
    m = MagicMock()
    m.role.value = role
    m.content = content
    m.abstained = kw.get("abstained", False)
    m.citations = kw.get("citations", [])
    m.retrieval_metadata = kw.get("md", {})
    return m


def test_notification_escapes_customer_content():
    transcript = notify._transcript([
        _msg("user", "<script>alert(1)</script> talk to a human"),
        _msg("assistant", "I don't know.", abstained=True,
             md={"abstention_reason": "insufficient_evidence"}),
    ])
    body = notify._html_body("Acme <b>", ["user_request", "abstain"], transcript, "https://x/y")
    assert "<script>" not in body and "&lt;script&gt;" in body and "Acme &lt;b&gt;" in body
    text = notify._text_body("Acme", ["abstain"], transcript, "https://x/y")
    assert "could not answer" in text and "abstained: insufficient_evidence" in text


async def test_deliver_reports_each_channel(monkeypatch):
    monkeypatch.setattr(notify.settings, "RESEND_API_KEY", "re_test")
    org = MagicMock(name="org")
    org.name = "Acme"
    org.settings = {"escalation": {"enabled": True, "emails": ["team@acme.com"],
                                   "slack_webhook_url": "https://hooks.slack.com/services/a/b/c"}}
    esc = MagicMock(id=uuid.uuid4(), reasons=["user_request"])
    with patch.object(notify, "_send_slack", AsyncMock()), patch.object(
        notify, "_send_email", AsyncMock(side_effect=RuntimeError("down"))
    ):
        out = await notify.deliver(esc, org, [_msg("user", "help")])
    assert out == {"slack": "sent", "email": "failed: RuntimeError"}
