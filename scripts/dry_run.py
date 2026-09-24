#!/usr/bin/env python3
"""Run the Semgrep + LLM review pipeline against a real local `git diff`,
with results printed to stdout instead of posted to GitHub. No GitHub App
or webhook needed — only LLM_API_KEY (from .env) for the LLM half; Semgrep
findings still show up even without it.

Usage:
    python scripts/dry_run.py --repo-path . --base main --head my-branch
"""

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from prreviewer.config import get_settings  # noqa: E402
from prreviewer.diffing import parse_diff  # noqa: E402
from prreviewer.findings import Finding, merge_findings  # noqa: E402
from prreviewer.llm.client import LLMClient  # noqa: E402
from prreviewer.llm.reviewer import review_file  # noqa: E402
from prreviewer.scanners.semgrep_scanner import scan_files  # noqa: E402
from prreviewer.worker import missing_test_hint_for  # noqa: E402


def git(repo_path: str, *args: str) -> str:
    result = subprocess.run(["git", "-C", repo_path, *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", default=".")
    parser.add_argument("--base", default="main")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()

    diff_text = git(args.repo_path, "diff", f"{args.base}...{args.head}")
    if not diff_text.strip():
        print("No diff between base and head.")
        return

    file_diffs = parse_diff(diff_text)
    file_paths = list(file_diffs.keys())

    file_contents: dict[str, str] = {}
    for path in file_paths:
        try:
            file_contents[path] = git(args.repo_path, "show", f"{args.head}:{path}")
        except RuntimeError:
            continue  # deleted or binary file

    print(f"Reviewing {len(file_paths)} changed file(s)...\n")

    semgrep_findings = await scan_files(file_contents)
    semgrep_findings = [
        f
        for f in semgrep_findings
        if (fd := file_diffs.get(f.file)) is not None and fd.overlaps_changed_range(f.start_line, f.end_line)
    ]

    settings = get_settings()
    llm_client = LLMClient(settings)
    missing_test_hint = missing_test_hint_for(set(file_paths))

    llm_findings: list[Finding] = []
    for path in file_paths:
        file_diff = file_diffs[path]
        per_file_diff = git(args.repo_path, "diff", f"{args.base}...{args.head}", "--", path)
        context = file_contents.get(path, per_file_diff)
        findings = await review_file(llm_client, path, file_diff, per_file_diff, context, missing_test_hint)
        llm_findings.extend(findings)

    merged = merge_findings(semgrep_findings, llm_findings)

    if not merged:
        print("No findings.")
        return

    for f in merged:
        print(f"{f.file}:{f.start_line}-{f.end_line} [{f.severity.value}/{f.category.value}] ({f.source}) {f.message}")
        if f.suggestion:
            print(f"    suggestion: {f.suggestion}")


if __name__ == "__main__":
    asyncio.run(main())
