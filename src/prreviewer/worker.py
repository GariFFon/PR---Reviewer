"""The ARQ task that runs one PR review end to end: fetch diff + files,
run Semgrep, run the LLM review per file, merge findings, publish. This is
the whole pipeline from ARCHITECTURE.md §4 minus the sandboxed-container
isolation and the separate triage/patch stages (Phase 2+).
"""

import logging

from arq.connections import RedisSettings

from .config import Settings, get_settings
from .diffing import parse_diff
from .findings import Finding, merge_findings
from .github.auth import InstallationTokenCache
from .github.client import GitHubClient, PRFile
from .llm.client import LLMClient
from .llm.reviewer import review_file
from .publisher.publish import publish_results
from .scanners.semgrep_scanner import scan_files

logger = logging.getLogger(__name__)

_TEST_PATH_MARKERS = ("/test/", "/tests/", "/__tests__/")
_SOURCE_EXTENSIONS = (".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".rb")


def latest_sha_key(repo: str, pr_number: int) -> str:
    return f"latest_sha:{repo}:{pr_number}"


def _looks_like_test(path: str) -> bool:
    lowered = f"/{path.lower()}"
    if any(marker in lowered for marker in _TEST_PATH_MARKERS):
        return True
    name = path.rsplit("/", 1)[-1].lower()
    return name.startswith("test_") or name.endswith(("_test.py", ".test.js", ".test.ts", ".spec.js", ".spec.ts"))


def _looks_like_source(path: str) -> bool:
    return path.lower().endswith(_SOURCE_EXTENSIONS) and not _looks_like_test(path)


def missing_test_hint_for(file_paths: set[str]) -> str | None:
    touches_source = any(_looks_like_source(p) for p in file_paths)
    touches_test = any(_looks_like_test(p) for p in file_paths)
    if touches_source and not touches_test:
        return (
            "Note: this pull request changes source files but none of the changed "
            "files match common test naming patterns (test_*, *_test.*, *.spec.*, "
            "or a tests/ directory). Consider flagging missing test coverage."
        )
    return None


async def startup(ctx: dict) -> None:
    settings = get_settings()
    ctx["settings"] = settings
    ctx["tokens"] = InstallationTokenCache(settings)
    ctx["llm_client"] = LLMClient(settings)


async def shutdown(ctx: dict) -> None:
    pass


async def run_review(ctx: dict, repo: str, pr_number: int, head_sha: str, installation_id: int) -> None:
    redis = ctx["redis"]
    key = latest_sha_key(repo, pr_number)

    latest = await redis.get(key)
    if latest is not None and latest.decode() != head_sha:
        logger.info("Skipping stale review for %s#%d (superseded)", repo, pr_number)
        return

    settings: Settings = ctx["settings"]
    tokens: InstallationTokenCache = ctx["tokens"]
    llm_client: LLMClient = ctx["llm_client"]
    github = GitHubClient(tokens, installation_id)

    check_run_id = await github.create_check_run(repo, head_sha)

    try:
        merged = await _review(github, llm_client, settings, repo, pr_number, head_sha)

        latest = await redis.get(key)
        if latest is not None and latest.decode() != head_sha:
            logger.info("Discarding completed review for %s#%d (superseded mid-run)", repo, pr_number)
            return

        await publish_results(github, repo, pr_number, check_run_id, merged)
    except Exception:
        logger.exception("Review failed for %s#%d", repo, pr_number)
        await github.complete_check_run(
            repo, check_run_id, "neutral", "PR Reviewer failed",
            "An internal error occurred while reviewing this pull request.", [],
        )


async def _review(
    github: GitHubClient, llm_client: LLMClient, settings: Settings, repo: str, pr_number: int, head_sha: str
) -> list[Finding]:
    diff_text = await github.get_pr_diff(repo, pr_number)
    file_diffs = parse_diff(diff_text)

    pr_files: list[PRFile] = await github.get_pr_files(repo, pr_number)
    pr_files = pr_files[: settings.max_files_per_pr]
    file_paths = {f.filename for f in pr_files}
    missing_test_hint = missing_test_hint_for(file_paths)

    file_contents: dict[str, str] = {}
    for pr_file in pr_files:
        if pr_file.status == "removed":
            continue
        content = await github.get_file_content(repo, pr_file.filename, head_sha)
        if content is None or len(content.encode("utf-8", errors="replace")) > settings.max_file_bytes:
            continue
        file_contents[pr_file.filename] = content

    semgrep_findings = await scan_files(file_contents)
    semgrep_findings = [
        f
        for f in semgrep_findings
        if (fd := file_diffs.get(f.file)) is not None and fd.overlaps_changed_range(f.start_line, f.end_line)
    ]

    llm_findings: list[Finding] = []
    for pr_file in pr_files:
        file_diff = file_diffs.get(pr_file.filename)
        if file_diff is None or not pr_file.patch:
            continue
        context = file_contents.get(pr_file.filename, pr_file.patch)
        findings = await review_file(
            llm_client, pr_file.filename, file_diff, pr_file.patch, context, missing_test_hint
        )
        llm_findings.extend(findings)

    return merge_findings(semgrep_findings, llm_findings)


class WorkerSettings:
    functions = [run_review]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
