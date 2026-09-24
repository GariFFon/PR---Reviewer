# Setup

## 1. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install semgrep
```

Redis must be running (`brew install redis` if you don't have it):

```bash
redis-server --daemonize yes
```

## 2. Create the GitHub App

1. Go to **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**.
2. Permissions (repository):
   - **Contents**: Read-only
   - **Pull requests**: Read & write
   - **Checks**: Read & write
3. Subscribe to events: **Pull request**.
4. Webhook URL: see step 3 below for exposing your local server.
5. Generate a **webhook secret** — put it in `.env` as `GITHUB_WEBHOOK_SECRET`.
6. Generate a **private key** (downloads a `.pem` file) — save it as `github-app-private-key.pem` in the repo root, and set `GITHUB_APP_PRIVATE_KEY_PATH` in `.env` if you put it elsewhere.
7. Note the **App ID** shown on the app's settings page — put it in `.env` as `GITHUB_APP_ID`.
8. Install the app on a scratch repository you don't mind testing against.

## 3. Expose your local server for webhooks

GitHub needs to reach your machine. Use `smee.io` (no account needed) or `ngrok`:

```bash
npx smee-client --url https://smee.io/<your-channel> --path /webhook/github --port 8000
```

Set the GitHub App's webhook URL to your smee/ngrok URL (the `/webhook/github` path must match).

## 4. Get an LLM API key

Sign up at [OpenRouter](https://openrouter.ai/settings/keys) (no payment method required) and put the key in `.env` as `LLM_API_KEY`. The default model, `z-ai/glm-5.2:free`, costs $0 per token but is rate-limited (roughly 50 requests/day with no credit ever added to the account, more after a one-time top-up). Free-tier models on OpenRouter occasionally return a 429 when their shared pool is busy — `review_file()` already degrades gracefully from this (Semgrep findings still post; that file's LLM findings are just skipped). `LLM_BASE_URL` / `LLM_MODEL` can point at any other OpenAI-compatible host (Together AI, Fireworks, OpenAI, DeepInfra, etc.) instead if you want a paid, higher-throughput model.

## 5. Configure

```bash
cp .env.example .env
# fill in GITHUB_APP_ID, GITHUB_WEBHOOK_SECRET, LLM_API_KEY
```

## 6. Run

```bash
scripts/run_dev.sh
```

This starts the FastAPI gateway on `:8000` and the ARQ worker together.

## 7. Verify

- **Fastest smoke test, no GitHub needed:** `python scripts/dry_run.py --repo-path . --base main --head <some-branch>` runs Semgrep + the LLM against a real local diff and prints findings to stdout.
- **Gateway smoke test:** with `run_dev.sh` running, `python scripts/simulate_webhook.py` posts a signed fixture payload and confirms signature verification + enqueueing work (GitHub API calls inside the worker will fail without a real installation — that's expected).
- **End to end:** open a real PR on the scratch repo you installed the app on. You should see a check run appear (in progress, then completed with a summary) and, if there are findings, a PR review with inline comments — with a one-click "Add suggestion" button where the fix is a concise single-hunk edit.

## Known limitations (Phase 1 MVP)

- Semgrep runs against downloaded file contents in a temp directory, not inside a real sandboxed container — fine for your own repos, not yet safe for scanning arbitrary third-party fork PRs.
- No Postgres or dashboard yet; results only show up in GitHub's own UI.
- No auto-opened "fix PR" — only inline `suggestion` comments the author applies manually.
- Dead-code and missing-test-coverage findings are best-effort (diff + file-list heuristics), not whole-program analysis.
