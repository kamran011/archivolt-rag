"""Per-organization handoff rules, stored in organizations.settings["escalation"].

Rules are data, not code, so an admin can change triggers and destinations without a deploy.
They are validated when saved through the API and again whenever they are used, so a value
written another way (a raw settings PATCH) can never send data somewhere unsafe."""

from __future__ import annotations

from typing import Literal

import structlog
from pydantic import BaseModel, EmailStr, Field, ValidationError, field_validator

logger = structlog.get_logger()

Trigger = Literal["user_request", "frustration", "abstain"]
ALL_TRIGGERS: list[Trigger] = ["user_request", "frustration", "abstain"]
SLACK_WEBHOOK_PREFIX = "https://hooks.slack.com/services/"
DEFAULT_CUSTOMER_MESSAGE = (
    "I've passed this conversation to our team, and someone will follow up with you."
)


class EscalationSettings(BaseModel):
    enabled: bool = False
    triggers: list[Trigger] = Field(default_factory=lambda: list(ALL_TRIGGERS))
    emails: list[EmailStr] = Field(default_factory=list, max_length=10)
    slack_webhook_url: str | None = None
    customer_message: str = Field(default=DEFAULT_CUSTOMER_MESSAGE, max_length=500)

    @field_validator("triggers")
    @classmethod
    def _dedupe(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))

    @field_validator("slack_webhook_url")
    @classmethod
    def _slack_only(cls, v: str | None) -> str | None:
        v = (v or "").strip() or None
        # Only Slack incoming webhooks: an arbitrary URL would let a settings write make the
        # server POST conversation data anywhere.
        if v is not None and not v.startswith(SLACK_WEBHOOK_PREFIX):
            raise ValueError(f"must be a Slack incoming webhook URL ({SLACK_WEBHOOK_PREFIX}...)")
        return v


def load_settings(org_settings: dict | None) -> EscalationSettings:
    raw = (org_settings or {}).get("escalation") or {}
    try:
        return EscalationSettings.model_validate(raw)
    except ValidationError as e:
        logger.warning("escalation_settings_invalid", error=str(e)[:300])
        return EscalationSettings()  # disabled
