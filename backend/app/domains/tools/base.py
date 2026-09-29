"""Tool framework for the bounded agent.

Every tool has: a Pydantic argument schema (validated before it runs), an authorization
check (enabled for this org / role), a timeout, a per-run call limit, and an audit record for
every attempt (including denied, invalid, timed-out and failed ones). The executor never
raises: a tool problem becomes an error result the agent can see, and the run continues or
stops under its own bounds.

Tenant scope (org, knowledge bases, access scope) lives in ToolContext and is fixed by the
caller. It is never a tool argument, so a model cannot choose whose data a tool reads.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domains.retrieval.access import AccessScope
from app.domains.retrieval.schemas import RetrievalFilters, RetrievedChunk
from app.models.organization_member import OrgRole

logger = structlog.get_logger()

AuditStatus = Literal["ok", "error", "timeout", "denied", "invalid", "limit", "unknown_tool"]
MAX_AUDIT_ARG_CHARS = 500


@dataclass
class ToolContext:
    db: AsyncSession
    org_id: uuid.UUID
    kb_ids: list[uuid.UUID]
    scope: AccessScope | None
    filters: RetrievalFilters | None = None
    user_id: uuid.UUID | None = None
    role: OrgRole | None = None
    org_settings: dict = field(default_factory=dict)
    # Text of internal evidence gathered so far in this run (used by the web-search
    # exfiltration guard).
    internal_texts: list[str] = field(default_factory=list)
    run_id: uuid.UUID = field(default_factory=uuid.uuid4)


class ToolResult(BaseModel):
    ok: bool = True
    content: str = ""  # what the planner sees
    chunks: list[RetrievedChunk] = []  # evidence, if the tool produces any
    error: str | None = None


class ToolAudit(BaseModel):
    run_id: uuid.UUID
    seq: int = 0  # order of the call within the run (timestamps tie inside a transaction)
    tool: str
    arguments: dict
    status: AuditStatus
    duration_ms: float
    result_chunks: int = 0
    detail: str | None = None


class Tool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    Args: ClassVar[type[BaseModel]]
    timeout_s: ClassVar[float | None] = None  # None -> settings.TOOL_TIMEOUT_S
    max_calls_per_run: ClassVar[int] = 3
    produces_evidence: ClassVar[bool] = True
    min_role: ClassVar[OrgRole | None] = None  # None: any org member

    def denied_reason(self, ctx: ToolContext) -> str | None:
        """Return why this tool may not run for this context, or None if allowed."""
        return None

    @abstractmethod
    async def run(self, ctx: ToolContext, args: Any) -> ToolResult: ...

    @classmethod
    def usage(cls) -> str:
        schema = cls.Args.model_json_schema().get("properties", {})
        fields = ", ".join(f'"{k}": <{v.get("type", "value")}>' for k, v in schema.items())
        return f'{{"action": "tool", "tool": "{cls.name}", "args": {{{fields}}}}}  ({cls.description})'


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def enabled_for(self, ctx: ToolContext) -> list[Tool]:
        return [t for t in self._tools.values() if t.denied_reason(ctx) is None]


_ROLE_RANK = {OrgRole.viewer: 0, OrgRole.member: 1, OrgRole.admin: 2, OrgRole.owner: 3}


def _truncate_args(args: Any) -> dict:
    if not isinstance(args, dict):
        return {"_raw": str(args)[:MAX_AUDIT_ARG_CHARS]}
    return {str(k)[:60]: str(v)[:MAX_AUDIT_ARG_CHARS] for k, v in list(args.items())[:20]}


class ToolExecutor:
    """Runs tools for one agent run: validation, authorization, limits, timeout, audit."""

    def __init__(self, registry: ToolRegistry, ctx: ToolContext) -> None:
        self.registry = registry
        self.ctx = ctx
        self.audit: list[ToolAudit] = []
        self._calls: dict[str, int] = {}

    def _record(self, tool: str, args: Any, status: AuditStatus, started: float, *,
                chunks: int = 0, detail: str | None = None) -> None:
        self.audit.append(
            ToolAudit(
                run_id=self.ctx.run_id,
                seq=len(self.audit),
                tool=tool[:60],
                arguments=_truncate_args(args),
                status=status,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                result_chunks=chunks,
                detail=(detail or None) and detail[:500],
            )
        )

    def record_internal(self, tool: str, args: Any, ok: bool, started: float, chunks: int = 0):
        """Audit an agent-internal action that is not a registry tool (outline, read_section)."""
        self._record(tool, args, "ok" if ok else "error", started, chunks=chunks)

    async def call(self, name: Any, raw_args: Any) -> ToolResult:
        started = time.perf_counter()
        tool = self.registry.get(name) if isinstance(name, str) else None
        if tool is None:
            self._record(str(name), raw_args, "unknown_tool", started)
            return ToolResult(ok=False, error=f"Unknown tool: {str(name)[:60]}")

        reason = tool.denied_reason(self.ctx)
        if reason is None and tool.min_role is not None:
            have = _ROLE_RANK.get(self.ctx.role, -1)
            if have < _ROLE_RANK[tool.min_role]:
                reason = f"requires role {tool.min_role.value}"
        if reason:
            self._record(tool.name, raw_args, "denied", started, detail=reason)
            return ToolResult(ok=False, error=f"Tool '{tool.name}' is not available: {reason}")

        if self._calls.get(tool.name, 0) >= tool.max_calls_per_run:
            self._record(tool.name, raw_args, "limit", started,
                         detail=f"limit {tool.max_calls_per_run}")
            return ToolResult(ok=False, error=f"Tool '{tool.name}' call limit reached")
        self._calls[tool.name] = self._calls.get(tool.name, 0) + 1

        try:
            args = tool.Args.model_validate(raw_args if isinstance(raw_args, dict) else {})
        except ValidationError as e:
            msg = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
            self._record(tool.name, raw_args, "invalid", started, detail=msg)
            return ToolResult(ok=False, error=f"Invalid arguments for '{tool.name}': {msg[:200]}")

        timeout = tool.timeout_s if tool.timeout_s is not None else settings.TOOL_TIMEOUT_S
        try:
            result = await asyncio.wait_for(tool.run(self.ctx, args), timeout=timeout)
        except TimeoutError:
            self._record(tool.name, raw_args, "timeout", started, detail=f"{timeout}s")
            return ToolResult(ok=False, error=f"Tool '{tool.name}' timed out")
        except Exception as e:  # a tool failure must not crash the run
            logger.warning("tool_failed", tool=tool.name, error=str(e))
            self._record(tool.name, raw_args, "error", started, detail=str(e))
            return ToolResult(ok=False, error=f"Tool '{tool.name}' failed")

        if not tool.produces_evidence:
            result.chunks = []  # a non-evidence tool can never smuggle in citable text
        self._record(tool.name, raw_args, "ok", started, chunks=len(result.chunks))
        return result
