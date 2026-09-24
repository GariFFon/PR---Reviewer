from prreviewer.findings import Category, Finding, Severity, merge_findings


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


def test_merge_concatenates_distinct_findings():
    a = _finding(message="finding A")
    b = _finding(start_line=20, end_line=20, message="finding B", source="llm")
    merged = merge_findings([a], [b])
    assert merged == [a, b]


def test_merge_drops_exact_duplicates():
    a = _finding(message="same finding")
    b = _finding(message="same finding", source="llm")
    merged = merge_findings([a], [b])
    assert len(merged) == 1


def test_merge_sorts_by_file_then_line_then_severity():
    low = _finding(start_line=5, end_line=5, severity=Severity.LOW, message="low")
    high = _finding(start_line=5, end_line=5, severity=Severity.CRITICAL, message="critical")
    later = _finding(start_line=50, end_line=50, message="later")
    merged = merge_findings([low, high, later])
    assert [f.message for f in merged] == ["critical", "low", "later"]


def test_overlaps():
    a = _finding(start_line=10, end_line=15)
    b = _finding(start_line=14, end_line=20)
    c = _finding(start_line=16, end_line=20)
    assert a.overlaps(b) is True
    assert a.overlaps(c) is False
