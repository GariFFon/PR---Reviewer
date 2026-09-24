"""Turn validated Finding objects into the exact shapes GitHub's Checks and
Reviews APIs expect. The bot never posts free-form model text — every field
here is either a fixed template or has passed through sanitize.scrub_before_posting.

Formatting aims for the same at-a-glance readability as GitHub's own Copilot
review comments (severity badges, a collapsible findings list, suggestion
diffs) using plain GitHub-flavored markdown only — emoji + tables + <details>
blocks render natively in a PR comment with no external images or HTML risk.
"""

from ..findings import Category, Finding, Severity
from ..sanitize import scrub_before_posting

_ANNOTATION_LEVEL = {
    Severity.CRITICAL: "failure",
    Severity.HIGH: "failure",
    Severity.MEDIUM: "warning",
    Severity.LOW: "notice",
    Severity.INFO: "notice",
}

_SEVERITY_EMOJI = {
    Severity.CRITICAL: "🟣",
    Severity.HIGH: "🔴",
    Severity.MEDIUM: "🟡",
    Severity.LOW: "🔵",
    Severity.INFO: "⚪",
}

_CATEGORY_EMOJI = {
    Category.SECURITY: "🛡️",
    Category.BUG: "🐛",
    Category.DEAD_CODE: "🧹",
    Category.TEST_COVERAGE: "🧪",
    Category.STYLE: "✨",
}

_SEVERITY_ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]


def _severity_rank(severity: Severity) -> int:
    return len(_SEVERITY_ORDER) - _SEVERITY_ORDER.index(severity)


def build_annotations(findings: list[Finding]) -> list[dict]:
    return [
        {
            "path": f.file,
            "start_line": f.start_line,
            "end_line": f.end_line,
            "annotation_level": _ANNOTATION_LEVEL[f.severity],
            "title": f"{f.category.value} ({f.severity.value})",
            "message": scrub_before_posting(f.message),
        }
        for f in findings
    ]


def build_check_summary(findings: list[Finding]) -> tuple[str, str, str]:
    """Returns (conclusion, title, summary markdown). Advisory only: this
    reviewer never fails a check by default, so a human still decides —
    matches ARCHITECTURE.md's suggest-only trust model."""
    if not findings:
        return "success", "No issues found", "PR Reviewer found no security or quality issues on the changed lines."

    by_severity: dict[Severity, int] = {}
    for f in findings:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1

    counts = ", ".join(
        f"{count} {severity.value}"
        for severity, count in sorted(by_severity.items(), key=lambda kv: -_severity_rank(kv[0]))
    )
    title = f"{len(findings)} finding(s): {counts}"
    lines = [f"PR Reviewer found **{len(findings)}** finding(s) on the changed lines ({counts}).", ""]
    for f in findings:
        emoji = _SEVERITY_EMOJI[f.severity]
        lines.append(f"- {emoji} `{f.file}:{f.start_line}` **[{f.severity.value}/{f.category.value}]** {scrub_before_posting(f.message)}")
    return "neutral", title, "\n".join(lines)


def build_review_comments(findings: list[Finding]) -> list[dict]:
    comments = []
    for f in findings:
        severity_emoji = _SEVERITY_EMOJI[f.severity]
        category_emoji = _CATEGORY_EMOJI[f.category]
        category_label = f.category.value.replace("_", " ").title()

        body_parts = [f"### {severity_emoji} {f.severity.value.title()} · {category_emoji} {category_label}"]
        tags = []
        if f.owasp:
            tags.append(f"**OWASP:** {f.owasp}")
        if f.cwe:
            tags.append(f"**CWE:** {f.cwe}")
        if tags:
            body_parts.append(" &nbsp;·&nbsp; ".join(tags))
        body_parts.append("")
        body_parts.append(scrub_before_posting(f.message))
        if f.suggestion and f.start_line and f.end_line:
            body_parts += ["", "```suggestion", scrub_before_posting(f.suggestion), "```"]

        comment: dict = {"path": f.file, "side": "RIGHT", "body": "\n".join(body_parts)}
        if f.end_line != f.start_line:
            comment["start_line"] = f.start_line
            comment["start_side"] = "RIGHT"
            comment["line"] = f.end_line
        else:
            comment["line"] = f.end_line
        comments.append(comment)
    return comments


def build_review_body(findings: list[Finding]) -> str:
    if not findings:
        return "## 🛡️ PR Reviewer\n\n✅ **No issues found** on the changed lines."

    by_severity: dict[Severity, int] = {}
    for f in findings:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
    ordered_severities = [s for s in _SEVERITY_ORDER if s in by_severity]

    has_blocking = any(s in by_severity for s in (Severity.CRITICAL, Severity.HIGH))
    status_line = "🟡 **Changes recommended**" if has_blocking else "🔵 **Minor issues found**"

    lines = [
        "## 🛡️ PR Reviewer",
        "",
        status_line,
        "",
        f"Found **{len(findings)}** finding(s) on the changed lines.",
        "",
        "| Severity | Count |",
        "|---|---|",
    ]
    for severity in ordered_severities:
        lines.append(f"| {_SEVERITY_EMOJI[severity]} {severity.value.title()} | {by_severity[severity]} |")

    lines += ["", f"<details>\n<summary><b>Findings ({len(findings)})</b></summary>", ""]
    for f in findings:
        severity_emoji = _SEVERITY_EMOJI[f.severity]
        category_emoji = _CATEGORY_EMOJI[f.category]
        lines.append(f"- {severity_emoji}{category_emoji} `{f.file}:{f.start_line}` — {scrub_before_posting(f.message)}")
    lines += ["", "</details>", "", "<sub>🛡️ Semgrep + LLM review · suggestions only, nothing auto-merges</sub>"]

    return "\n".join(lines)
