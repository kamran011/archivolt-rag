import re
from collections.abc import Callable

_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def split_table(table_text: str, max_tokens: int, count_tokens: Callable[[str], int]) -> list[str]:
    """Splits a table on row boundaries, repeating the header row(s) on every
    piece so each piece is self-describing. A single row larger than the budget
    is kept whole rather than cut mid-row."""
    lines = [ln for ln in table_text.split("\n") if ln.strip()]
    if not lines or count_tokens(table_text) <= max_tokens:
        return [table_text]

    header_len = 2 if len(lines) > 1 and _SEPARATOR_RE.match(lines[1]) else 1
    header = lines[:header_len]
    rows = lines[header_len:]
    if not rows:
        return [table_text]

    header_text = "\n".join(header)
    header_tokens = count_tokens(header_text)

    pieces: list[str] = []
    current: list[str] = []
    current_tokens = header_tokens
    for row in rows:
        row_tokens = count_tokens(row)
        if current and current_tokens + row_tokens > max_tokens:
            pieces.append("\n".join([header_text, *current]))
            current, current_tokens = [], header_tokens
        current.append(row)
        current_tokens += row_tokens
    if current:
        pieces.append("\n".join([header_text, *current]))
    return pieces


def rows_to_markdown(rows: list[list[str | None]]) -> str:
    """Renders extracted table rows as a GitHub-style markdown table."""
    cleaned = [
        [(c or "").replace("\n", " ").replace("|", "\\|").strip() for c in row]
        for row in rows
        if any((c or "").strip() for c in row)
    ]
    if not cleaned:
        return ""
    width = max(len(r) for r in cleaned)
    cleaned = [r + [""] * (width - len(r)) for r in cleaned]
    lines = ["| " + " | ".join(cleaned[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in cleaned[1:]]
    return "\n".join(lines)
