"""Stateless webhook gateway (ARCHITECTURE.md §3/§4 step 1-2): verify the
signature, filter events, enqueue, return fast. All the actual work happens
in the ARQ worker (worker.py).
"""

import logging
from contextlib import asynccontextmanager

from arq import create_pool
from fastapi import FastAPI, HTTPException, Request, Response

from .config import get_settings
from .github.signature import verify_signature
from .queue import enqueue_review, redis_settings_from

logger = logging.getLogger(__name__)

HANDLED_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.redis = await create_pool(redis_settings_from(settings))
    yield
    await app.state.redis.close()


app = FastAPI(title="PR Reviewer", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.post("/webhook/github", status_code=202)
async def github_webhook(request: Request) -> Response:
    settings = get_settings()
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    if not verify_signature(raw_body, signature, settings.github_webhook_secret):
        raise HTTPException(status_code=401, detail="invalid signature")

    event = request.headers.get("X-GitHub-Event")
    if event != "pull_request":
        return Response(status_code=202)

    payload = await request.json()
    action = payload.get("action")
    pr = payload.get("pull_request", {})

    if action not in HANDLED_ACTIONS:
        return Response(status_code=202)
    if pr.get("draft") and action != "ready_for_review":
        return Response(status_code=202)
    if settings.skip_bot_authors and pr.get("user", {}).get("login", "").endswith("[bot]"):
        return Response(status_code=202)

    repo = payload["repository"]["full_name"]
    pr_number = pr["number"]
    head_sha = pr["head"]["sha"]
    installation_id = payload["installation"]["id"]

    logger.info("Queueing review for %s#%d @ %s", repo, pr_number, head_sha)
    await enqueue_review(request.app.state.redis, repo, pr_number, head_sha, installation_id)

    return Response(status_code=202)
