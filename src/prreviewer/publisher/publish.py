from ..findings import Finding
from ..github.client import GitHubClient
from .formatting import build_annotations, build_check_summary, build_review_body, build_review_comments


async def publish_results(
    github: GitHubClient,
    repo: str,
    pr_number: int,
    check_run_id: int,
    findings: list[Finding],
) -> None:
    conclusion, title, summary = build_check_summary(findings)
    annotations = build_annotations(findings)
    await github.complete_check_run(repo, check_run_id, conclusion, title, summary, annotations)

    comments = build_review_comments(findings)
    body = build_review_body(findings)
    await github.create_review(repo, pr_number, body, comments)
