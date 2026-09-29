"""Safe arithmetic for the agent. A whitelist AST walk — never eval() — with hard limits on
input length, nesting, magnitude and exponent size, so no expression can hang or blow up
memory. Results are computed values for the planner, not evidence: they cannot be cited."""

from __future__ import annotations

import ast
import math
import operator
import re
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from app.domains.tools.base import Tool, ToolContext, ToolResult

MAX_EXPRESSION_CHARS = 200
MAX_DEPTH = 25
MAX_ABS_VALUE = 1e30
MAX_EXPONENT = 64

_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"abs": abs, "round": round, "min": min, "max": max}


class CalcError(ValueError):
    pass


def _check(value: float | int) -> float | int:
    if isinstance(value, complex) or (isinstance(value, float) and not math.isfinite(value)):
        raise CalcError("result is not a finite number")
    if abs(value) > MAX_ABS_VALUE:
        raise CalcError("number too large")
    return value


def _eval(node: ast.AST, depth: int = 0) -> float | int:
    if depth > MAX_DEPTH:
        raise CalcError("expression too deeply nested")
    if isinstance(node, ast.Expression):
        return _eval(node.body, depth + 1)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise CalcError("only numbers are allowed")
        return _check(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _check(_UNARY[type(node.op)](_eval(node.operand, depth + 1)))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _eval(node.left, depth + 1), _eval(node.right, depth + 1)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise CalcError("exponent too large")
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise CalcError("division by zero")
        try:
            return _check(_BIN[type(node.op)](left, right))
        except OverflowError as e:
            raise CalcError("number too large") from e
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        if node.keywords or not 1 <= len(node.args) <= 6:
            raise CalcError("unsupported function call")
        return _check(_FUNCS[node.func.id](*[_eval(a, depth + 1) for a in node.args]))
    raise CalcError("unsupported expression")


_CALL_RE = re.compile(r"[A-Za-z_]\s*\(")
_DIGIT_GROUP_RE = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")


def _strip_digit_groups(expression: str) -> str:
    """'1,200 * 3' -> '1200 * 3'. Commas are only digit-group separators when the expression
    has no function call; inside max(3, 900) they separate arguments and must be kept."""
    if _CALL_RE.search(expression):
        return expression
    return _DIGIT_GROUP_RE.sub("", expression)


def calculate(expression: str) -> float | int:
    """Evaluate an arithmetic expression. Raises CalcError for anything else."""
    expression = expression.strip()
    if not expression or len(expression) > MAX_EXPRESSION_CHARS:
        raise CalcError("expression is empty or too long")
    try:
        tree = ast.parse(_strip_digit_groups(expression), mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as e:
        raise CalcError("not a valid arithmetic expression") from e
    try:
        return _eval(tree)
    except RecursionError as e:
        raise CalcError("expression too deeply nested") from e


class CalculatorTool(Tool):
    name: ClassVar[str] = "calculator"
    description: ClassVar[str] = (
        "evaluate arithmetic (+ - * / // % **, parentheses, abs/round/min/max) on numbers "
        "you already found; the result is a computed value, not a citable source"
    )
    produces_evidence: ClassVar[bool] = False
    max_calls_per_run: ClassVar[int] = 5

    class Args(BaseModel):
        expression: str = Field(min_length=1, max_length=MAX_EXPRESSION_CHARS)

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        try:
            value = calculate(args.expression)
        except CalcError as e:
            return ToolResult(ok=False, error=f"calculator: {e}")
        shown = round(value, 10) if isinstance(value, float) else value
        return ToolResult(content=f"{args.expression.strip()} = {shown}")
