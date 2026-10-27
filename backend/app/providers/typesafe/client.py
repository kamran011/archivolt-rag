"""Minimal client for TypeSafe's System One API (Jev).

POST {JEV_BASE_URL}/v1/systemone with `Authorization: Bearer <key>` and
{"model", "state", "questions"}; the response is {"model", "answers", "usage"}, answers keyed
by the question names we chose. Schema: https://api.typesafe.ai/openapi.json.

A failed call raises `TypeSafeError`. Callers must treat that as "no answer", never as a
"no" (TypeSafe guidance), so it never silently becomes a decision.
"""

from __future__ import annotations

import httpx
import structlog
from pydantic import BaseModel

from app.config import settings

logger = structlog.get_logger()

SYSTEM_ONE_PATH = "/v1/systemone"


class TypeSafeError(Exception):
    pass


class SystemOneResponse(BaseModel):
    model: str
    answers: dict[str, dict]
    usage: dict

    def noul(self, name: str) -> float:
        answer = self.answers.get(name)
        if not answer or answer.get("type") != "noul" or not isinstance(answer.get("noul"), int | float):
            raise TypeSafeError(f"missing noul answer '{name}'")
        return float(answer["noul"])


def configured() -> bool:
    return bool(settings.JEV_API_KEY)


async def system_one(
    state: dict | list | str,
    questions: dict[str, dict],
    *,
    client: httpx.AsyncClient | None = None,
) -> SystemOneResponse:
    if not configured():
        raise TypeSafeError("JEV_API_KEY / TYPESAFE_API_KEY is not set")
    url = settings.JEV_BASE_URL.rstrip("/") + SYSTEM_ONE_PATH
    payload = {"model": settings.JEV_MODEL, "state": state, "questions": questions}
    headers = {"Authorization": f"Bearer {settings.JEV_API_KEY}"}
    # Log the exact request shape (never the key) so any answer can be reproduced.
    logger.debug("typesafe_request", model=settings.JEV_MODEL, questions=list(questions))
    try:
        if client is not None:
            resp = await client.post(url, json=payload, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=settings.JEV_TIMEOUT_S) as c:
                resp = await c.post(url, json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise TypeSafeError(f"request failed: {type(e).__name__}") from e
    if resp.status_code != 200:
        detail = resp.text[:300]
        raise TypeSafeError(f"HTTP {resp.status_code}: {detail}")
    try:
        return SystemOneResponse.model_validate(resp.json())
    except Exception as e:
        raise TypeSafeError("malformed response") from e
