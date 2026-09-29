"""
Heuristic prompt-injection detection for ingested document content.

This is a DETECTION/AUDIT tool, not a blocking filter — per the platform's
security model (master spec section 38), injected-looking text inside a
document is still legitimate document content and must still be ingested
and made searchable. The actual defense against injection is architectural:
the RAG system prompt (app/domains/rag/prompts.py) explicitly frames
retrieved content as untrusted evidence, never as instructions, and the
citation parser only trusts source indices that map to evidence the
caller actually supplied.

What this module is for: flagging documents so operators can audit them,
and giving the security test suite something concrete to assert against.
"""

import re

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ignore_instructions", re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I)),
    ("reveal_system_prompt", re.compile(r"reveal\s+(your\s+)?(system\s+prompt|instructions)", re.I)),
    ("disregard_rules", re.compile(r"disregard\s+(the\s+)?(rules|guidelines|instructions)", re.I)),
    ("new_instructions", re.compile(r"(new|updated)\s+instructions?\s*:", re.I)),
    ("role_override", re.compile(r"you\s+are\s+now\s+(a|an)\b", re.I)),
    ("act_as", re.compile(r"act\s+as\s+(if\s+you\s+are\s+)?(a|an)\b", re.I)),
    ("exfiltration_request", re.compile(r"(send|email|post)\s+(this|the\s+above|all\s+data)\b.{0,40}\bto\b", re.I)),
    ("system_tag_injection", re.compile(r"<\s*(system|assistant)\s*>", re.I)),
]


def scan_for_injection_patterns(text: str) -> list[str]:
    """Returns the names of any suspicious instruction-like patterns found
    in the text. An empty list means nothing matched — not a guarantee the
    content is safe, just that it didn't trip these heuristics."""
    matched = []
    for name, pattern in _PATTERNS:
        if pattern.search(text):
            matched.append(name)
    return matched
