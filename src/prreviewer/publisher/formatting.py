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

_SEVERITY_LABEL = {
    Severity.CRITICAL: "Critical",
    Severity.HIGH: "High",
    Severity.MEDIUM: "Medium",
    Severity.LOW: "Low",
    Severity.INFO: "Info",
}

_CATEGORY_EMOJI = {
    Category.SECURITY: "🛡️",
    Category.BUG: "🐛",
    Category.DEAD_CODE: "🧹",
    Category.TEST_COVERAGE: "🧪",
    Category.STYLE: "✨",
}

_CATEGORY_LABEL = {
    Category.SECURITY: "Security",
    Category.BUG: "Bug Risk",
    Category.DEAD_CODE: "Dead Code",
    Category.TEST_COVERAGE: "Test Coverage",
    Category.STYLE: "Code Style",
}

_SEVERITY_ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]


def _severity_rank(severity: Severity) -> int:
    return len(_SEVERITY_ORDER) - _SEVERITY_ORDER.index(severity)


def _severity_badge(severity: Severity) -> str:
    """A compact inline badge for severity."""
    return f"{_SEVERITY_EMOJI[severity]} **{_SEVERITY_LABEL[severity]}**"


def _category_badge(category: Category) -> str:
    return f"{_CATEGORY_EMOJI[category]} {_CATEGORY_LABEL[category]}"


def build_annotations(findings: list[Finding]) -> list[dict]:
    return [
        {
            "path": f.file,
            "start_line": f.start_line,
            "end_line": f.end_line,
            "annotation_level": _ANNOTATION_LEVEL[f.severity],
            "title": f"{_SEVERITY_LABEL[f.severity]} · {_CATEGORY_LABEL[f.category]}",
            "message": scrub_before_posting(f.message),
        }
        for f in findings
    ]


def build_check_summary(findings: list[Finding]) -> tuple[str, str, str]:
    """Returns (conclusion, title, summary markdown). Advisory only: this
    reviewer never fails a check by default, so a human still decides —
    matches ARCHITECTURE.md's suggest-only trust model."""
    if not findings:
        return (
            "success",
            "✅ Clean — No issues found",
            (
                "## <img src=\"https://raw.githubusercontent.com/Yash77179/landing_page/master/logo.png\" width=\"20\" height=\"20\" /> PR Security Reviewer\n\n"
                "**No security or quality issues detected** on the changed lines.\n\n"
                "---\n"
                "<sub>Powered by Semgrep + AI · suggestions only, nothing auto-merges</sub>"
            ),
        )

    by_severity: dict[Severity, int] = {}
    for f in findings:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1

    counts = " · ".join(
        f"{_SEVERITY_EMOJI[severity]} {count} {_SEVERITY_LABEL[severity]}"
        for severity, count in sorted(by_severity.items(), key=lambda kv: -_severity_rank(kv[0]))
    )
    title = f"{'🚨' if any(s in by_severity for s in (Severity.CRITICAL, Severity.HIGH)) else '⚠️'} {len(findings)} finding(s)"

    lines = [
        "## <img src=\"https://raw.githubusercontent.com/Yash77179/landing_page/master/logo.png\" width=\"20\" height=\"20\" /> PR Security Reviewer",
        "",
        f"> **{len(findings)} finding(s)** detected on the changed lines",
        f"> {counts}",
        "",
    ]

    # Group findings by file
    by_file: dict[str, list[Finding]] = {}
    for f in findings:
        by_file.setdefault(f.file, []).append(f)

    lines.append("| File | Findings | Highest Severity |")
    lines.append("|:-----|:--------:|:----------------:|")
    for file_path, file_findings in by_file.items():
        highest = max(file_findings, key=lambda f: _severity_rank(f.severity))
        lines.append(f"| `{file_path}` | {len(file_findings)} | {_severity_badge(highest.severity)} |")

    lines += [
        "",
        "---",
        "<sub>Powered by Semgrep + AI · suggestions only, nothing auto-merges</sub>",
    ]
    return "neutral", title, "\n".join(lines)


def build_review_comments(findings: list[Finding]) -> list[dict]:
    comments = []
    for f in findings:
        severity_emoji = _SEVERITY_EMOJI[f.severity]
        category_emoji = _CATEGORY_EMOJI[f.category]
        severity_label = _SEVERITY_LABEL[f.severity]
        category_label = _CATEGORY_LABEL[f.category]

        # Header with severity and category badges
        body_parts = [
            f"#### {severity_emoji} {severity_label} · {category_emoji} {category_label}",
        ]

        # Tags row (OWASP / CWE) in a blockquote for visual distinction
        tags = []
        if f.owasp:
            tags.append(f"`{f.owasp}`")
        if f.cwe:
            tags.append(f"`{f.cwe}`")
        if f.confidence is not None:
            confidence_pct = int(f.confidence * 100)
            tags.append(f"Confidence: **{confidence_pct}%**")
        if tags:
            body_parts.append(f"> {' · '.join(tags)}")
            body_parts.append("")

        # Main message
        body_parts.append(scrub_before_posting(f.message))

        # Suggestion block
        if f.suggestion and f.start_line and f.end_line:
            body_parts += [
                "",
                "<details>",
                "<summary>💡 <b>Suggested fix</b></summary>",
                "",
                "```suggestion",
                scrub_before_posting(f.suggestion),
                "```",
                "",
                "</details>",
            ]

        # Footer
        source_label = {"semgrep": "Semgrep", "llm": "AI Review", "sanitize": "Sanitizer"}.get(f.source, f.source)
        body_parts += [
            "",
            f"<sub>Source: {source_label}{f' · Rule: `{f.rule_id}`' if f.rule_id else ''}</sub>",
        ]

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
        return (
            "## <img src=\"https://raw.githubusercontent.com/Yash77179/landing_page/master/logo.png\" width=\"20\" height=\"20\" /> PR Security Reviewer\n\n"
            "### ✅ All Clear!\n\n"
            "No security or quality issues found on the changed lines.\n\n"
            "> Your code passed both **static analysis** (Semgrep) and **AI-powered review** checks.\n\n"
            "---\n"
            "<sub>🛡️ Powered by Semgrep + AI · suggestions only, nothing auto-merges</sub>"
        )

    by_severity: dict[Severity, int] = {}
    by_category: dict[Category, int] = {}
    for f in findings:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
        by_category[f.category] = by_category.get(f.category, 0) + 1

    ordered_severities = [s for s in _SEVERITY_ORDER if s in by_severity]
    has_blocking = any(s in by_severity for s in (Severity.CRITICAL, Severity.HIGH))

    if has_blocking:
        status_icon = "🚨"
        status_text = "Action Required"
        status_detail = "Critical or high severity issues were found that should be addressed before merging."
    else:
        status_icon = "⚠️"
        status_text = "Review Recommended"
        status_detail = "Minor issues were found. Please review the suggestions below."

    lines = [
        "## <img src=\"https://raw.githubusercontent.com/Yash77179/landing_page/master/logo.png\" width=\"20\" height=\"20\" /> PR Security Reviewer",
        "",
        f"### {status_icon} {status_text}",
        "",
        f"> {status_detail}",
        "",
        "---",
        "",
        "#### 📊 Summary",
        "",
    ]

    # Severity breakdown table
    lines.append("| Severity | Count |")
    lines.append("|:---------|:-----:|")
    for severity in ordered_severities:
        lines.append(f"| {_SEVERITY_EMOJI[severity]} **{_SEVERITY_LABEL[severity]}** | {by_severity[severity]} |")
    lines.append("")

    # Category breakdown
    category_tags = []
    for category, count in sorted(by_category.items(), key=lambda kv: -kv[1]):
        category_tags.append(f"{_CATEGORY_EMOJI[category]} {_CATEGORY_LABEL[category]}: **{count}**")
    lines.append(" · ".join(category_tags))
    lines.append("")

    # Collapsible detailed findings list
    lines.append("---")
    lines.append("")
    lines.append(f"<details>")
    lines.append(f"<summary><b>📋 All Findings ({len(findings)})</b></summary>")
    lines.append("")

    # Group by file
    by_file: dict[str, list[Finding]] = {}
    for f in findings:
        by_file.setdefault(f.file, []).append(f)

    for file_path, file_findings in by_file.items():
        lines.append(f"**`{file_path}`**")
        lines.append("")
        for f in file_findings:
            severity_emoji = _SEVERITY_EMOJI[f.severity]
            category_emoji = _CATEGORY_EMOJI[f.category]
            msg = scrub_before_posting(f.message)
            # Truncate long messages for the summary view
            short_msg = msg[:120] + "…" if len(msg) > 120 else msg
            tags = ""
            if f.owasp or f.cwe:
                tag_parts = [t for t in [f.owasp, f.cwe] if t]
                tags = f" `{'` `'.join(tag_parts)}`"
            lines.append(f"- {severity_emoji}{category_emoji} **L{f.start_line}** — {short_msg}{tags}")
        lines.append("")

    lines.append("</details>")
    lines.append("")
    lines.append("---")
    lines.append("<sub>🛡️ Powered by Semgrep + AI · suggestions only, nothing auto-merges</sub>")

    return "\n".join(lines)
