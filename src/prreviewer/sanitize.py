"""Injection hardening (ARCHITECTURE.md §6): the PR diff is attacker-controlled
input. Anything sent to the LLM has HTML comments and invisible Unicode
stripped first, and their presence is itself reported as a finding. Anything
the LLM produces is scrubbed before it's ever posted back to GitHub.
"""

import re

from .findings import Category, Finding, Severity

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# Zero-width and bidi-control characters used in real prompt-injection attacks
# to hide instructions from a human reviewer while an LLM still reads them.
_INVISIBLE_CHARS = (
    "​"  # zero-width space
    "‌"  # zero-width non-joiner
    "‍"  # zero-width joiner
    "⁠"  # word joiner
    "﻿"  # BOM / zero-width no-break space
    "\u202A\u202B\u202C\u202D\u202E"  # LRE/RLE/PDF/LRO/RLO
    "\u2066\u2067\u2068\u2069"  # LRI/RLI/FSI/PDI
)
_INVISIBLE_RE = re.compile(f"[{_INVISIBLE_CHARS}]")

_URL_RE = re.compile(r"https?://\S+")
_MENTION_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_-]+")
_SECRET_LIKE_RE = re.compile(
    r"(?:sk|pk|ghp|gho|ghs|xox[baprs])-?[A-Za-z0-9_]{16,}|AKIA[0-9A-Z]{16}"
)

MAX_POSTED_FIELD_LEN = 2000


def sanitize_for_llm(file_path: str, text: str) -> tuple[str, Finding | None]:
    """Strip HTML comments and invisible Unicode before code reaches the LLM.
    Returns the cleaned text plus a Finding flagging the strip, if anything
    was actually removed (an injection attempt's likeliest goal is silence,
    so its presence is signal, never silently discarded)."""
    stripped_comments = _HTML_COMMENT_RE.sub("", text)
    cleaned = _INVISIBLE_RE.sub("", stripped_comments)

    if cleaned == text:
        return text, None

    finding = Finding(
        file=file_path,
        start_line=1,
        end_line=1,
        category=Category.SECURITY,
        severity=Severity.MEDIUM,
        message=(
            "Diff contains hidden HTML comments and/or invisible Unicode "
            "control characters. These are stripped before analysis but "
            "their presence may indicate a prompt-injection attempt."
        ),
        source="sanitize",
    )
    return cleaned, finding


def scrub_before_posting(text: str) -> str:
    """Never let free-form model text reach GitHub unfiltered: cap length,
    drop bare URLs, @-mentions, and secret-shaped strings."""
    scrubbed = _URL_RE.sub("[link removed]", text)
    scrubbed = _MENTION_RE.sub("[mention removed]", scrubbed)
    scrubbed = _SECRET_LIKE_RE.sub("[redacted]", scrubbed)
    if len(scrubbed) > MAX_POSTED_FIELD_LEN:
        scrubbed = scrubbed[: MAX_POSTED_FIELD_LEN - 1].rstrip() + "…"
    return scrubbed
