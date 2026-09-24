#!/usr/bin/env python3
"""POST a correctly-signed fixture `pull_request` webhook at a running
gateway, to smoke-test signature verification, event filtering, and
enqueueing without needing a real GitHub App or a real PR.

Usage:
    uvicorn prreviewer.app:app &          # or scripts/run_dev.sh
    python scripts/simulate_webhook.py
"""

import argparse
import hashlib
import hmac
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from prreviewer.config import get_settings  # noqa: E402

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "sample_webhook_payload.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000/webhook/github")
    parser.add_argument("--fixture", default=str(FIXTURE_PATH))
    args = parser.parse_args()

    settings = get_settings()
    if not settings.github_webhook_secret:
        raise SystemExit("GITHUB_WEBHOOK_SECRET is not set (check your .env)")

    body = Path(args.fixture).read_bytes()
    signature = "sha256=" + hmac.new(settings.github_webhook_secret.encode(), body, hashlib.sha256).hexdigest()

    request = urllib.request.Request(
        args.url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": signature,
        },
    )
    with urllib.request.urlopen(request) as response:
        print(f"status={response.status}")
        print(response.read().decode() or "(empty body)")


if __name__ == "__main__":
    main()
