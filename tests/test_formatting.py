from prreviewer.findings import Category, Finding, Severity
from prreviewer.publisher.formatting import build_check_summary, build_review_body, build_review_comments


def _finding(**overrides) -> Finding:
    defaults = dict(
        file="app.py",
        start_line=10,
        end_line=10,
        category=Category.SECURITY,
        severity=Severity.HIGH,
        message="SQL injection",
        source="semgrep",
    )
    defaults.update(overrides)
    return Finding(**defaults)


def test_review_body_no_findings():
    body = build_review_body([])
    assert "No issues found" in body


def test_review_body_lists_severity_counts_and_findings():
    findings = [
        _finding(severity=Severity.HIGH, message="SQL injection"),
        _finding(severity=Severity.LOW, category=Category.DEAD_CODE, message="unused var"),
    ]
    body = build_review_body(findings)
    assert "Changes recommended" in body
    assert "| 🔴 High | 1 |" in body
    assert "| 🔵 Low | 1 |" in body
    assert "SQL injection" in body
    assert "unused var" in body
    assert "<details>" in body and "</details>" in body


def test_review_body_no_blocking_severities_is_minor():
    findings = [_finding(severity=Severity.LOW, category=Category.STYLE, message="simplify this")]
    body = build_review_body(findings)
    assert "Minor issues found" in body


def test_review_comment_includes_header_tags_and_suggestion():
    finding = _finding(
        owasp="A05:2025 Injection",
        cwe="CWE-89",
        suggestion="cur.execute('SELECT 1')",
    )
    comments = build_review_comments([finding])
    body = comments[0]["body"]
    assert "High" in body and "Security" in body
    assert "A05:2025 Injection" in body
    assert "CWE-89" in body
    assert "```suggestion" in body
    assert "cur.execute('SELECT 1')" in body


def test_review_comment_line_range_single_vs_multiline():
    single = build_review_comments([_finding(start_line=5, end_line=5)])[0]
    assert single["line"] == 5
    assert "start_line" not in single

    multi = build_review_comments([_finding(start_line=5, end_line=8)])[0]
    assert multi["start_line"] == 5
    assert multi["line"] == 8


def test_check_summary_empty():
    conclusion, title, summary = build_check_summary([])
    assert conclusion == "success"


def test_check_summary_with_findings():
    conclusion, title, summary = build_check_summary([_finding()])
    assert conclusion == "neutral"
    assert "1" in title
    assert "🔴" in summary
