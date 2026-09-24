"""Turn validated Finding objects into the exact shapes GitHub's Checks and
Reviews APIs expect. The bot never posts free-form model text — every field
here is either a fixed template or has passed through sanitize.scrub_before_posting.
"""

from ..findings import Finding, Severity
from ..sanitize import scrub_before_posting

_ANNOTATION_LEVEL = {
    Severity.CRITICAL: "failure",
    Severity.HIGH: "failure",
    Severity.MEDIUM: "warning",
    Severity.LOW: "notice",
    Severity.INFO: "notice",
}


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

    counts = ", ".join(f"{count} {severity.value}" for severity, count in sorted(by_severity.items(), key=lambda kv: -_severity_rank(kv[0])))
    title = f"{len(findings)} finding(s): {counts}"
    lines = [f"PR Reviewer found **{len(findings)}** finding(s) on the changed lines ({counts}).", ""]
    for f in findings:
        lines.append(f"- `{f.file}:{f.start_line}` **[{f.severity.value}/{f.category.value}]** {scrub_before_posting(f.message)}")
    return "neutral", title, "\n".join(lines)


def _severity_rank(severity: Severity) -> int:
    order = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]
    return len(order) - order.index(severity)


def build_review_comments(findings: list[Finding]) -> list[dict]:
    comments = []
    for f in findings:
        body_parts = [f"**[{f.severity.value}] {f.category.value}**"]
        if f.owasp:
            body_parts.append(f"OWASP: {f.owasp}")
        if f.cwe:
            body_parts.append(f"CWE: {f.cwe}")
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
        return "PR Reviewer: no issues found on the changed lines."
    return f"PR Reviewer found {len(findings)} finding(s) on the changed lines. See inline comments."
