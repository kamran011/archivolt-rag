"""external_api: read-only retrieval from an application API the deployment has allowlisted.

For live application data (order status, inventory, CRM records) that does not belong in
the knowledge base. Controls, all of which must hold: the source is in the deployment's
EXTERNAL_API_SOURCES allowlist (the model only ever picks a *name*, never a URL), the
organization has opted in (settings.external_api_enabled), HTTPS only, GET only, no
redirects, a response size cap, JSON responses only. Parameters are scalars and screened by
the same exfiltration guard as web search so internal text and secrets cannot leave in a
query string. Results are untrusted external content: labelled `source=external` and put
through the normal rerank/filter/gate/verification like any other evidence.

EXTERNAL_API_SOURCES is a JSON object:
  {"orders": {"url": "https://api.example.com/orders", "description": "order status by id",
              "auth_header": "Authorization", "auth_value": "Bearer ..."}}
"""

from __future__ import annotations

import json
import uuid
from typing import Any, ClassVar
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

from app.config import settings
from app.domains.retrieval.schemas import RetrievedChunk
from app.domains.tools.base import Tool, ToolContext, ToolResult
from app.domains.tools.web_search import _clean, query_violation

MAX_PARAMS = 5
MAX_PARAM_CHARS = 200
MAX_RESPONSE_BYTES = 200_000
MAX_CONTENT_CHARS = 1500
EXTERNAL_API_SCORE = 0.7


def load_sources() -> dict[str, dict]:
    raw = settings.EXTERNAL_API_SOURCES.strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    sources = {}
    for name, cfg in data.items():
        if not isinstance(cfg, dict) or not isinstance(cfg.get("url"), str):
            continue
        parts = urlsplit(cfg["url"])
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            continue  # HTTPS only, no embedded credentials
        sources[str(name)] = cfg
    return sources


async def fetch_json(url: str, params: dict, headers: dict) -> Any:
    """GET with a hard size cap, no redirects. Raises on non-2xx or non-JSON."""
    async with httpx.AsyncClient(timeout=settings.TOOL_TIMEOUT_S, follow_redirects=False) as client:
        async with client.stream("GET", url, params=params, headers=headers) as resp:
            resp.raise_for_status()
            if "json" not in resp.headers.get("content-type", ""):
                raise ValueError("response is not JSON")
            body = b""
            async for part in resp.aiter_bytes():
                body += part
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ValueError("response too large")
    return json.loads(body)


class ExternalApiTool(Tool):
    name: ClassVar[str] = "external_api"
    description: ClassVar[str] = (
        "fetch live application data from an allowlisted read-only API "
        "(source is a configured name; params are simple key/value filters)"
    )
    max_calls_per_run: ClassVar[int] = 2

    class Args(BaseModel):
        source: str = Field(min_length=1, max_length=60)
        params: dict[str, str | int | float | bool] = Field(default_factory=dict)

    def denied_reason(self, ctx: ToolContext) -> str | None:
        if not load_sources():
            return "no external API sources are configured on this deployment"
        if ctx.org_settings.get("external_api_enabled") is not True:
            return "external API retrieval is not enabled for this organization"
        return None

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        sources = load_sources()
        cfg = sources.get(args.source)
        if cfg is None:
            return ToolResult(
                ok=False, error=f"unknown source '{args.source[:60]}'; available: {sorted(sources)}"
            )
        if len(args.params) > MAX_PARAMS:
            return ToolResult(ok=False, error=f"at most {MAX_PARAMS} params")
        params = {}
        for key, value in args.params.items():
            text = _clean(str(value))
            if len(key) > 60 or len(text) > MAX_PARAM_CHARS:
                return ToolResult(ok=False, error="param too long")
            violation = query_violation(text, ctx.internal_texts)
            if violation:
                return ToolResult(ok=False, error=f"external_api blocked: {violation}")
            params[key] = text

        headers = {}
        if cfg.get("auth_header") and cfg.get("auth_value"):
            headers[str(cfg["auth_header"])] = str(cfg["auth_value"])
        try:
            data = await fetch_json(cfg["url"], params, headers)
        except Exception as e:  # network/HTTP/format problems become a visible tool error
            return ToolResult(ok=False, error=f"{args.source} request failed: {type(e).__name__}")

        description = str(cfg.get("description") or args.source)[:200]
        text = _clean(json.dumps(data, ensure_ascii=False, default=str))[:MAX_CONTENT_CHARS]
        ident = uuid.uuid5(uuid.NAMESPACE_URL, f"{cfg['url']}?{json.dumps(params, sort_keys=True)}")
        chunk = RetrievedChunk(
            chunk_id=ident,
            document_id=ident,
            document_title=f"API: {args.source}",
            content=f"{description}: {text}",
            score=EXTERNAL_API_SCORE,
            metadata={
                "source": "external",
                "url": cfg["url"],
                "derived_from": [f"external_api:{args.source}"],
                "content_type": "api_result",
            },
            retrieval_method="external_api",
            is_current=True,
            authority_tier="standard",
        )
        return ToolResult(content=f"1 result from {args.source}", chunks=[chunk])
