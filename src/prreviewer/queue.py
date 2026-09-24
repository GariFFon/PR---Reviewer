"""ARQ job queue wiring. A job is keyed on repo+PR number: enqueueing also
records the head_sha as "latest" for that PR, so a worker picking up a stale
job (superseded by a force-push) can bail out cheaply instead of doing a
full review that would just be thrown away.
"""

from arq.connections import ArqRedis, RedisSettings

from .config import Settings
from .worker import WorkerSettings, latest_sha_key  # noqa: F401  (WorkerSettings resolved by `arq prreviewer.queue.WorkerSettings`)


def redis_settings_from(settings: Settings) -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis_url)


async def enqueue_review(redis: ArqRedis, repo: str, pr_number: int, head_sha: str, installation_id: int) -> None:
    await redis.set(latest_sha_key(repo, pr_number), head_sha)
    await redis.enqueue_job("run_review", repo, pr_number, head_sha, installation_id)
