"""Thin async GitHub REST client. Only the calls the reviewer needs: read a
PR's diff and touched files, read file contents at a ref, and post results
back as a check run + a PR review. No other GitHub surface is touched.
"""

import base64
from dataclasses import dataclass

import httpx

from .auth import InstallationTokenCache

_GITHUB_API = "https://api.github.com"


@dataclass
class PRFile:
    filename: str
    status: str  # added | removed | modified | renamed
    patch: str | None  # unified diff hunk for this file; absent for binary/too-large files


class GitHubClient:
    def __init__(self, tokens: InstallationTokenCache, installation_id: int):
        self._tokens = tokens
        self._installation_id = installation_id

    async def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        token = await self._tokens.get_token(self._installation_id)
        return {"Authorization": f"Bearer {token}", "Accept": accept}

    async def get_pr_diff(self, repo: str, pr_number: int) -> str:
        headers = await self._headers(accept="application/vnd.github.v3.diff")
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{_GITHUB_API}/repos/{repo}/pulls/{pr_number}", headers=headers)
            response.raise_for_status()
            return response.text

    async def get_pr_files(self, repo: str, pr_number: int) -> list[PRFile]:
        headers = await self._headers()
        files: list[PRFile] = []
        url = f"{_GITHUB_API}/repos/{repo}/pulls/{pr_number}/files"
        async with httpx.AsyncClient() as client:
            while url:
                response = await client.get(url, headers=headers, params={"per_page": 100})
                response.raise_for_status()
                for item in response.json():
                    files.append(PRFile(filename=item["filename"], status=item["status"], patch=item.get("patch")))
                url = response.links.get("next", {}).get("url")
        return files

    async def get_file_content(self, repo: str, path: str, ref: str) -> str | None:
        headers = await self._headers()
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{_GITHUB_API}/repos/{repo}/contents/{path}", headers=headers, params={"ref": ref}
            )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        if data.get("encoding") != "base64":
            return None
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    async def create_check_run(self, repo: str, head_sha: str, name: str = "PR Reviewer") -> int:
        headers = await self._headers()
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{_GITHUB_API}/repos/{repo}/check-runs",
                headers=headers,
                json={"name": name, "head_sha": head_sha, "status": "in_progress"},
            )
            response.raise_for_status()
            return response.json()["id"]

    async def complete_check_run(
        self,
        repo: str,
        check_run_id: int,
        conclusion: str,
        title: str,
        summary: str,
        annotations: list[dict],
    ) -> None:
        headers = await self._headers()
        async with httpx.AsyncClient() as client:
            # The Checks API accepts at most 50 annotations per request.
            for i in range(0, max(len(annotations), 1), 50):
                batch = annotations[i : i + 50]
                is_last = i + 50 >= len(annotations)
                payload = {
                    "status": "completed",
                    "output": {"title": title, "summary": summary, "annotations": batch},
                }
                if is_last:
                    payload["conclusion"] = conclusion
                response = await client.patch(
                    f"{_GITHUB_API}/repos/{repo}/check-runs/{check_run_id}", headers=headers, json=payload
                )
                response.raise_for_status()

    async def create_review(self, repo: str, pr_number: int, body: str, comments: list[dict]) -> None:
        if not comments and not body:
            return
        headers = await self._headers()
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{_GITHUB_API}/repos/{repo}/pulls/{pr_number}/reviews",
                headers=headers,
                json={"body": body, "event": "COMMENT", "comments": comments},
            )
            response.raise_for_status()
