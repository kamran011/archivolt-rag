import asyncio
import uuid
from typing import ClassVar

import pytest
from pydantic import BaseModel, Field

from app.config import settings
from app.domains.retrieval.schemas import RetrievedChunk
from app.domains.tools.base import Tool, ToolContext, ToolExecutor, ToolRegistry, ToolResult
from app.domains.tools.calculator import (
    MAX_EXPRESSION_CHARS,
    CalcError,
    CalculatorTool,
    calculate,
)
from app.models.organization_member import OrgRole


def chunk(text="evidence") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(), document_id=uuid.uuid4(), document_title="d", content=text,
        score=0.9, metadata={}, retrieval_method="tool",
    )


class EchoTool(Tool):
    name: ClassVar[str] = "echo"
    description: ClassVar[str] = "echo the text"
    max_calls_per_run: ClassVar[int] = 2

    class Args(BaseModel):
        text: str = Field(min_length=1, max_length=20)
        times: int = Field(default=1, ge=1, le=3)

    async def run(self, ctx, args):
        return ToolResult(content=args.text * args.times, chunks=[chunk(args.text)])


class SlowTool(Tool):
    name: ClassVar[str] = "slow"
    description: ClassVar[str] = "never finishes in time"
    timeout_s: ClassVar[float | None] = 0.05

    class Args(BaseModel):
        pass

    async def run(self, ctx, args):
        await asyncio.sleep(5)
        return ToolResult()


class BoomTool(Tool):
    name: ClassVar[str] = "boom"
    description: ClassVar[str] = "raises"

    class Args(BaseModel):
        pass

    async def run(self, ctx, args):
        raise RuntimeError("secret internal detail: db password=hunter2")


class AdminOnlyTool(Tool):
    name: ClassVar[str] = "admin_only"
    description: ClassVar[str] = "needs admin"
    min_role: ClassVar[OrgRole | None] = OrgRole.admin

    class Args(BaseModel):
        pass

    async def run(self, ctx, args):
        return ToolResult(content="ok")


class DisabledTool(Tool):
    name: ClassVar[str] = "disabled"
    description: ClassVar[str] = "off for this org"

    class Args(BaseModel):
        pass

    def denied_reason(self, ctx):
        return "not enabled for this organization"

    async def run(self, ctx, args):
        return ToolResult()


class SmugglerTool(Tool):
    """A non-evidence tool that (wrongly) returns chunks: the executor must drop them."""

    name: ClassVar[str] = "smuggler"
    description: ClassVar[str] = "x"
    produces_evidence: ClassVar[bool] = False

    class Args(BaseModel):
        pass

    async def run(self, ctx, args):
        return ToolResult(content="value", chunks=[chunk("citable?")])


def make_executor(role=OrgRole.member) -> ToolExecutor:
    registry = ToolRegistry()
    for t in (EchoTool(), SlowTool(), BoomTool(), AdminOnlyTool(), DisabledTool(), SmugglerTool()):
        registry.register(t)
    ctx = ToolContext(db=None, org_id=uuid.uuid4(), kb_ids=[], scope=None, role=role)
    return ToolExecutor(registry, ctx)


def statuses(ex):
    return [(a.tool, a.status) for a in ex.audit]


@pytest.mark.asyncio
async def test_ok_call_returns_evidence_and_is_audited():
    ex = make_executor()
    r = await ex.call("echo", {"text": "hi", "times": 2})
    assert r.ok and r.content == "hihi" and len(r.chunks) == 1
    assert statuses(ex) == [("echo", "ok")]
    assert ex.audit[0].result_chunks == 1 and ex.audit[0].arguments == {"text": "hi", "times": "2"}


@pytest.mark.asyncio
async def test_unknown_tool_is_rejected_and_audited():
    ex = make_executor()
    for name in ("does_not_exist", None, 42, "../etc"):
        r = await ex.call(name, {})
        assert not r.ok and "Unknown tool" in r.error
    assert all(s == "unknown_tool" for _, s in statuses(ex)) and len(ex.audit) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args",
    [{}, {"text": ""}, {"text": "x" * 21}, {"text": "a", "times": 9}, {"text": "a", "times": "many"},
     "not a dict", None],
)
async def test_invalid_arguments_never_reach_the_tool(args):
    ex = make_executor()
    r = await ex.call("echo", args)
    assert not r.ok and r.error.startswith("Invalid arguments")
    assert statuses(ex) == [("echo", "invalid")]


@pytest.mark.asyncio
async def test_per_run_call_limit():
    ex = make_executor()
    assert (await ex.call("echo", {"text": "a"})).ok
    assert (await ex.call("echo", {"text": "b"})).ok
    r = await ex.call("echo", {"text": "c"})
    assert not r.ok and "limit" in r.error
    assert statuses(ex) == [("echo", "ok"), ("echo", "ok"), ("echo", "limit")]


@pytest.mark.asyncio
async def test_timeout_is_enforced():
    ex = make_executor()
    r = await ex.call("slow", {})
    assert not r.ok and "timed out" in r.error
    assert statuses(ex) == [("slow", "timeout")]
    assert ex.audit[0].duration_ms < 2000


@pytest.mark.asyncio
async def test_default_timeout_comes_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "TOOL_TIMEOUT_S", 0.05)

    class Slow2(SlowTool):
        name: ClassVar[str] = "slow2"
        timeout_s: ClassVar[float | None] = None

    ex = make_executor()
    ex.registry.register(Slow2())
    assert (await ex.call("slow2", {})).error == "Tool 'slow2' timed out"


@pytest.mark.asyncio
async def test_tool_exception_is_contained_and_not_leaked_to_the_planner():
    ex = make_executor()
    r = await ex.call("boom", {})
    assert not r.ok
    assert "hunter2" not in (r.error or "") and "hunter2" not in r.content  # nothing internal
    assert statuses(ex) == [("boom", "error")]
    assert "hunter2" in ex.audit[0].detail  # ...but the audit log keeps it for operators


@pytest.mark.asyncio
async def test_role_and_enablement_authorization():
    member = make_executor(OrgRole.member)
    assert not (await member.call("admin_only", {})).ok
    assert not (await member.call("disabled", {})).ok
    assert statuses(member) == [("admin_only", "denied"), ("disabled", "denied")]

    admin = make_executor(OrgRole.admin)
    assert (await admin.call("admin_only", {})).ok
    assert not (await admin.call("disabled", {})).ok  # enablement is independent of role

    viewer = make_executor(OrgRole.viewer)
    assert not (await viewer.call("admin_only", {})).ok

    no_role = make_executor(None)
    assert not (await no_role.call("admin_only", {})).ok


@pytest.mark.asyncio
async def test_non_evidence_tools_cannot_smuggle_citable_chunks():
    ex = make_executor()
    r = await ex.call("smuggler", {})
    assert r.ok and r.content == "value" and r.chunks == []


@pytest.mark.asyncio
async def test_audit_truncates_long_arguments():
    ex = make_executor()
    await ex.call("echo", {"text": "x" * 5000})  # invalid (too long) but still audited
    assert len(ex.audit[0].arguments["text"]) <= 500


def test_registry_and_usage_text():
    registry = ToolRegistry()
    registry.register(EchoTool())
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register(EchoTool())
    usage = EchoTool.usage()
    assert '"tool": "echo"' in usage and '"text"' in usage and "echo the text" in usage
    ctx = ToolContext(db=None, org_id=uuid.uuid4(), kb_ids=[], scope=None)
    assert [t.name for t in registry.enabled_for(ctx)] == ["echo"]


# --- calculator -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("1 + 2 * 3", 7),
        ("(1 + 2) * 3", 9),
        ("10 / 4", 2.5),
        ("10 // 4", 2),
        ("10 % 4", 2),
        ("2 ** 10", 1024),
        ("-5 + +3", -2),
        ("1,200 * 3", 3600),
        ("1,234,567 + 1", 1234568),
        ("max(3, 900)", 900),
        ("max(1,200) + 1", 201),
        ("round(2.567, 1)", 2.6),
        ("max(3, 9, 4) - min(3, 9, 4)", 6),
        ("abs(-7.5)", 7.5),
        ("1e3 + 1", 1001.0),
    ],
)
def test_calculator_evaluates(expr, expected):
    assert calculate(expr) == expected


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('id')",
        "().__class__.__bases__",
        "open('/etc/passwd')",
        "eval('1')",
        "x + 1",
        "'a' * 3",
        "[1, 2][0]",
        "lambda: 1",
        "1 if True else 2",
        "True + 1",
        "1 +",
        "",
        "   ",
        "2 ** 1000",
        "9 ** 9 ** 9",
        "10 ** 40",
        "1 / 0",
        "5 % 0",
        "1e308 * 10",
        "abs()",
        "1,2 + 3",
        "round(1, 2, 3, 4, 5, 6, 7)",
        "max(key=abs)",
        "a" * (MAX_EXPRESSION_CHARS + 1),
        "(" * 500 + "1" + ")" * 500,
        "1" + "+1" * 100 + "**" * 50,
    ],
)
def test_calculator_rejects_everything_unsafe(expr):
    with pytest.raises(CalcError):
        calculate(expr)


@pytest.mark.asyncio
async def test_calculator_tool_through_executor():
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    ex = ToolExecutor(registry, ToolContext(db=None, org_id=uuid.uuid4(), kb_ids=[], scope=None))
    ok = await ex.call("calculator", {"expression": "1200 * 0.15"})
    assert ok.ok and ok.content == "1200 * 0.15 = 180.0" and ok.chunks == []
    bad = await ex.call("calculator", {"expression": "__import__('os')"})
    assert not bad.ok and "calculator" in bad.error
    # The tool ran but rejected the input: audited as an error, with the reason.
    assert statuses(ex) == [("calculator", "ok"), ("calculator", "error")]
    assert "not a valid" in ex.audit[1].detail or "unsupported" in ex.audit[1].detail
