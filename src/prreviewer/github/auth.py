"""GitHub App authentication: sign a short-lived JWT with the App's private
key, exchange it for a per-installation access token, cache until near
expiry. This is what lets the bot create check runs and post reviews with
its own identity instead of a personal access token.
"""

import time

import httpx
import jwt

from ..config import Settings

_GITHUB_API = "https://api.github.com"
_JWT_TTL_SECONDS = 9 * 60  # GitHub allows up to 10 minutes; stay under it
_TOKEN_REFRESH_MARGIN_SECONDS = 60


class InstallationTokenCache:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._tokens: dict[int, tuple[str, float]] = {}  # installation_id -> (token, expires_at)

    def _app_jwt(self) -> str:
        now = int(time.time())
        payload = {"iat": now - 5, "exp": now + _JWT_TTL_SECONDS, "iss": self._settings.github_app_id}
        return jwt.encode(payload, self._settings.github_app_private_key, algorithm="RS256")

    async def get_token(self, installation_id: int) -> str:
        cached = self._tokens.get(installation_id)
        if cached and cached[1] - _TOKEN_REFRESH_MARGIN_SECONDS > time.time():
            return cached[0]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{_GITHUB_API}/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {self._app_jwt()}",
                    "Accept": "application/vnd.github+json",
                },
            )
            response.raise_for_status()
            data = response.json()

        expires_at = time.time() + 55 * 60  # tokens are valid 1h; refresh a bit early
        self._tokens[installation_id] = (data["token"], expires_at)
        return data["token"]
