"""Run Semgrep against the PR's touched files and normalize its output into
the shared Finding model. This is Stage 1 (Detect) from ARCHITECTURE.md:
cheap, deterministic, high-recall candidates for injection, XSS, secrets,
weak crypto, vulnerable patterns.

Runs as a plain subprocess against downloaded file contents (not a real
clone in an isolated container) — an explicit MVP simplification, fine for
a self-reviewed repo, not yet safe for arbitrary third-party fork PRs.
"""

import asyncio
import json
import tempfile
from pathlib import Path

from ..findings import Category, Finding, Severity

RULESETS = ["p/security-audit", "p/owasp-top-ten", "p/ci"]
TIMEOUT_SECONDS = 120

_SEVERITY_MAP = {
    "ERROR": Severity.HIGH,
    "WARNING": Severity.MEDIUM,
    "INFO": Severity.LOW,
}


async def scan_files(files: dict[str, str]) -> list[Finding]:
    """`files` maps repo-relative path -> file content. Returns findings with
    file paths matching the keys of `files`."""
    if not files:
        return []

    with tempfile.TemporaryDirectory(prefix="prreviewer-semgrep-") as workspace:
        workspace_path = Path(workspace)
        for relative_path, content in files.items():
            target = workspace_path / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", errors="replace")

        args = ["semgrep", "scan", "--json", "--quiet", "--metrics=off"]
        for ruleset in RULESETS:
            args += ["--config", ruleset]
        args.append(str(workspace_path))

        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=TIMEOUT_SECONDS)
        except TimeoutError:
            process.kill()
            return []

        if not stdout:
            return []

        try:
            report = json.loads(stdout)
        except json.JSONDecodeError:
            return []

        findings: list[Finding] = []
        for result in report.get("results", []):
            relative_path = str(Path(result["path"]).relative_to(workspace_path))
            start_line = result["start"]["line"]
            end_line = result["end"]["line"]
            extra = result.get("extra", {})
            findings.append(
                Finding(
                    file=relative_path,
                    start_line=start_line,
                    end_line=end_line,
                    category=Category.SECURITY,
                    severity=_SEVERITY_MAP.get(extra.get("severity", "WARNING"), Severity.MEDIUM),
                    message=extra.get("message", result.get("check_id", "Semgrep finding")),
                    source="semgrep",
                    rule_id=result.get("check_id"),
                    cwe=_first_cwe(extra),
                )
            )
        return findings


def _first_cwe(extra: dict) -> str | None:
    metadata = extra.get("metadata", {})
    cwe = metadata.get("cwe")
    if isinstance(cwe, list):
        return cwe[0] if cwe else None
    return cwe
