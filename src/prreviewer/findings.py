from enum import StrEnum

from pydantic import BaseModel, Field


class Category(StrEnum):
    SECURITY = "security"
    BUG = "bug"
    DEAD_CODE = "dead_code"
    TEST_COVERAGE = "test_coverage"
    STYLE = "style"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


_SEVERITY_ORDER = {
    Severity.CRITICAL: 4,
    Severity.HIGH: 3,
    Severity.MEDIUM: 2,
    Severity.LOW: 1,
    Severity.INFO: 0,
}


class Finding(BaseModel):
    file: str
    start_line: int
    end_line: int
    category: Category
    severity: Severity
    message: str
    source: str  # "semgrep" | "llm" | "sanitize"
    rule_id: str | None = None
    owasp: str | None = None
    cwe: str | None = None
    suggestion: str | None = None
    confidence: float | None = None

    def overlaps(self, other: "Finding") -> bool:
        return self.file == other.file and self.start_line <= other.end_line and other.start_line <= self.end_line


def merge_findings(*groups: list[Finding]) -> list[Finding]:
    """Concatenate findings from multiple sources, drop exact duplicates
    (same file + line range + message), sort by file then line then severity."""
    seen: set[tuple[str, int, int, str]] = set()
    merged: list[Finding] = []
    for group in groups:
        for finding in group:
            key = (finding.file, finding.start_line, finding.end_line, finding.message)
            if key in seen:
                continue
            seen.add(key)
            merged.append(finding)

    merged.sort(key=lambda f: (f.file, f.start_line, -_SEVERITY_ORDER[f.severity]))
    return merged
