"""Turning tabular cells into typed, normalized records for structured queries."""

import re

_INT_RE = re.compile(r"^-?\d{1,15}$")
_FLOAT_RE = re.compile(r"^-?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$")
MAX_COLUMN_NAME = 60


def typed_value(cell):
    """'12' -> 12, '3.5' -> 3.5, everything else stays text. Non-strings pass through."""
    if not isinstance(cell, str):
        return cell
    text = cell.strip()
    if _INT_RE.match(text):
        return int(text)
    if _FLOAT_RE.match(text) and len(text) <= 30:
        try:
            value = float(text)
        except ValueError:
            return cell
        return value if value == value and abs(value) != float("inf") else cell
    return cell


def normalize_columns(header: list[str]) -> list[str]:
    """Trim, fill blanks (col_N) and de-duplicate (name, name_2, ...) header names."""
    names: list[str] = []
    seen: set[str] = set()
    for i, raw in enumerate(header, start=1):
        base = (str(raw).strip() or f"col_{i}")[:MAX_COLUMN_NAME]
        name, n = base, 2
        while name.lower() in seen:
            name = f"{base}_{n}"[:MAX_COLUMN_NAME]
            n += 1
        seen.add(name.lower())
        names.append(name)
    return names


def build_records(header: list[str], rows: list[list]) -> tuple[list[str], list[dict]]:
    columns = normalize_columns(header)
    records = [
        {col: typed_value(row[i]) for i, col in enumerate(columns) if i < len(row)} for row in rows
    ]
    return columns, records
