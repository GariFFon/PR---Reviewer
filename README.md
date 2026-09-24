# PR Reviewer

A GitHub App that automatically reviews pull requests: it runs Semgrep against the changed files and sends each changed file through an LLM review pass, then posts the combined findings back to GitHub as a check run and an inline-comment PR review. Nothing is auto-applied — every finding is a suggestion a human decides on.

**Stack:** FastAPI (webhook gateway) · Redis + ARQ (job queue/worker) · Semgrep (static analysis) · any OpenAI-compatible LLM endpoint (default: OpenRouter, free tier) · GitHub Apps API.

This is the Phase 1 MVP described in [ARCHITECTURE.md](ARCHITECTURE.md); see that doc for the full multi-phase design (triage stage, autofix, dashboard) and the reasoning behind each decision. This README describes what's actually implemented today.

## Contents

- [How it works](#how-it-works)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Testing](#testing)
- [Known limitations](#known-limitations)
- [Roadmap](#roadmap)

## How it works

1. GitHub sends a `pull_request` webhook when a PR is opened, updated, or marked ready for review.
2. The gateway verifies the webhook signature and enqueues a review job; a newer push to the same PR supersedes an older queued/in-flight one.
3. A worker fetches the PR's diff and changed files, runs Semgrep on them, and sends each changed file to an LLM for a second-pass review (logic bugs, dead code, missing tests, style).
4. Findings from both are merged, deduplicated, and filtered so that **only lines the PR actually touched** are ever reported on.
5. Results are posted back as a GitHub check run (pass/neutral, with annotations) and a PR review with inline comments — `suggestion` blocks where a fix is a confident single-hunk edit.

## Architecture

### System diagram

```
                              ┌──────────────────────────────┐
                              │   GitHub (pull_request event)│
                              └───────────────┬───────────────┘
                                               │ webhook, HMAC-signed
                                               ▼
                    ┌──────────────────────────────────────────────┐
                    │  FastAPI gateway  —  app.py                  │
                    │  • verify X-Hub-Signature-256                │
                    │  • filter: action, draft, bot author         │
                    │  • enqueue job, return 202 (stateless)       │
                    └───────────────────┬────────────────────────────┘
                                        │ enqueue_review()
                                        ▼
                          ┌───────────────────────────────┐
                          │  Redis — ARQ job queue         │
                          │  latest_sha:<repo>:<pr_number> │
                          └───────────────┬─────────────────┘
                                        │ run_review job
                                        ▼
        ┌──────────────────────────────────────────────────────────────────┐
        │                    ARQ worker  —  worker.py                       │
        │                                                                    │
        │  1. bail out if a newer push already superseded this job          │
        │  2. create a GitHub check run ("in progress")                     │
        │  3. fetch PR diff + changed files  (github/client.py,             │
        │     authenticated via a per-installation token, github/auth.py)   │
        │  4. parse the diff into a changed-line map  (diffing.py)          │
        │                                                                    │
        │   ┌────────────────────────┐     ┌─────────────────────────────┐  │
        │   │ Semgrep scanner         │     │ LLM reviewer                 │  │
        │   │ scanners/semgrep_       │     │ llm/reviewer.py               │  │
        │   │ scanner.py               │     │                               │  │
        │   │                          │     │ sanitize.py strips hidden     │  │
        │   │ p/security-audit         │     │ HTML/Unicode → build prompt   │  │
        │   │ p/owasp-top-ten          │     │ (llm/prompts.py) → call       │  │
        │   │ p/ci                     │     │ OpenAI-compatible endpoint    │  │
        │   │                          │     │ (llm/client.py) → validate    │  │
        │   │ runs against a temp      │     │ JSON against schema, retry    │  │
        │   │ workspace of downloaded  │     │ once on malformed output      │  │
        │   │ file contents            │     │                               │  │
        │   └────────────┬─────────────┘     └───────────────┬───────────────┘  │
        │                │   findings kept only if they land on a changed line  │
        │                └───────────────────────┬────────────────────────────┘ │
        │                                        ▼                              │
        │                     merge_findings()  —  findings.py                 │
        │                     dedupe (file+line+message) · sort by severity    │
        └───────────────────────────────┬──────────────────────────────────────┘
                                        │
                                        ▼
                      ┌──────────────────────────────────┐
                      │  Publisher  —  publisher/         │
                      │  • every field passed through     │
                      │    scrub_before_posting()          │
                      │    (sanitize.py) before posting    │
                      │  • build check-run summary +       │
                      │    annotations (formatting.py)     │
                      │  • build PR review body + inline   │
                      │    comments, batched 50/request     │
                      └───────────────┬────────────────────┘
                                        │
                                        ▼
                          ┌─────────────────────────────┐
                          │  GitHub check run            │
                          │  + PR review (COMMENT event) │
                          │  suggestions only — nothing   │
                          │  auto-merges                  │
                          └─────────────────────────────┘
```

### Components

| Component | File(s) | Responsibility |
|---|---|---|
| Webhook gateway | `app.py` | Stateless FastAPI app. Verifies `X-Hub-Signature-256`, filters to `opened`/`synchronize`/`reopened`/`ready_for_review` (skips drafts and, by default, bot authors), enqueues a job, returns `202` immediately. |
| Job queue | `queue.py` | ARQ (Redis-backed). Jobs are keyed on `repo + PR number`; enqueueing also records the head SHA as "latest" so a stale job can cheaply bail out. |
| Worker / orchestrator | `worker.py` | The `run_review` ARQ task: end-to-end pipeline for one PR — fetch, scan, review, merge, publish. Re-checks for a superseding push both before and after the scan/review work. |
| Diff parser | `diffing.py` | Parses a unified diff into a per-file set of changed line numbers (right/new side only). Every finding, from either source, is filtered through this — nothing is ever reported on an untouched line. |
| GitHub auth | `github/auth.py` | Signs a short-lived App JWT (RS256), exchanges it for a per-installation access token, caches until near expiry. |
| GitHub client | `github/client.py` | Thin async REST client: PR diff, PR file list, file contents at a ref, create/complete check run, create PR review. Nothing else is touched. |
| Signature verification | `github/signature.py` | Constant-time HMAC-SHA256 check of the webhook payload. |
| Semgrep scanner | `scanners/semgrep_scanner.py` | Writes changed file contents into a temp workspace, runs `semgrep scan` with `p/security-audit`, `p/owasp-top-ten`, `p/ci`, and normalizes results into `Finding` objects. |
| LLM client | `llm/client.py` | Thin wrapper around an OpenAI-compatible chat completions endpoint (swappable via `LLM_BASE_URL`/`LLM_MODEL`). |
| LLM prompts | `llm/prompts.py` | System prompt (fences the diff as untrusted data, forbids treating it as instructions, forces a strict JSON schema) and user-message construction. |
| LLM reviewer | `llm/reviewer.py` | Orchestrates one review call per changed file: sanitize → prompt → call → parse/validate JSON → retry once on failure → degrade gracefully (drop only that file's LLM findings) rather than fail the whole PR. |
| Injection hardening | `sanitize.py` | Strips HTML comments and invisible/bidi Unicode before anything reaches the LLM (and reports their presence as a finding); scrubs URLs, @-mentions, secret-shaped strings, and length-caps anything before it's posted back to GitHub. |
| Findings model | `findings.py` | Shared `Finding` schema (`Category`, `Severity`, file/line/message/source/…), plus `merge_findings()` (dedupe + severity sort). |
| Publisher | `publisher/formatting.py`, `publisher/publish.py` | Turns `Finding` lists into GitHub Checks annotations, a check-run summary, and a PR review (body + inline comments with `suggestion` blocks), styled like GitHub's own Copilot review UI. |
| Config | `config.py` | `pydantic-settings`-based `Settings`, loaded from `.env`. |

### Request lifecycle

1. **Webhook arrives** at `POST /webhook/github`. Signature is verified; non-`pull_request` events, unhandled actions, drafts (unless just marked ready), and bot authors (configurable) are dropped with a `202`.
2. **Job is queued** in Redis, keyed on `repo#pr_number`, with the head SHA recorded as "latest" for that key.
3. **Worker picks up the job.** If the recorded "latest" SHA no longer matches (a newer push arrived), the job is dropped — no wasted scan.
4. **Check run is created** on GitHub as `in_progress`.
5. **PR diff and files are fetched** via a per-installation token (minted from the App's private key, cached until near expiry, never handed to the LLM). Files over `MAX_FILE_BYTES` or beyond `MAX_FILES_PER_PR` are skipped.
6. **Semgrep runs** against the downloaded file contents, then its findings are filtered to only the lines the diff actually changed.
7. **The LLM reviews each changed file** independently: input is sanitized, a schema-locked prompt is sent, the response is parsed and validated (one retry on malformed JSON), and findings are again filtered to changed lines only. A finding's `suggestion` is only kept if the model's confidence is ≥ 0.6.
8. **Findings are merged**, deduplicated, and sorted by severity. The "still latest SHA?" check runs again here, in case a new push landed mid-review.
9. **Results are published**: the check run completes with a summary + annotations (batched 50 at a time, the Checks API limit), and a single PR review is posted with inline comments. All model-generated text passes through `scrub_before_posting()` first — the bot never posts free-form model output unfiltered.

If anything in steps 4–8 raises, the check run is completed as `neutral` with a generic failure message rather than left hanging.

### Finding data model

Every finding — whether from Semgrep, the LLM, or the sanitizer itself — is normalized to the same shape (`findings.py`):

```json
{
  "file": "api/orders.py",
  "start_line": 42, "end_line": 44,
  "category": "security",           // security | bug | dead_code | test_coverage | style
  "severity": "high",               // critical | high | medium | low | info
  "message": "SQL query is built with an f-string from user input.",
  "source": "semgrep",              // semgrep | llm | sanitize
  "owasp": "A05:2025 Injection",
  "cwe": "CWE-89",
  "suggestion": "cur.execute(\"SELECT * FROM orders WHERE id=%s\", (oid,))",
  "confidence": 0.9
}
```

### Security design of the reviewer itself

A PR's contents are attacker-controlled input, so the pipeline treats them that way:

- **The LLM has no tools, shell, network, or credentials** — it only ever returns JSON that plain code then validates and acts on.
- **Untrusted content is fenced.** Diff and file context are wrapped in `<diff>`/`<file_context>` tags the system prompt explicitly marks as data, never instructions; the PR title, body, and commit messages are never sent at all.
- **Hidden-instruction techniques are stripped and flagged**, not silently dropped: HTML comments and invisible/bidi Unicode are removed before the LLM sees them, and their presence is itself reported as a medium-severity finding (`sanitize.sanitize_for_llm`).
- **Everything posted back is filtered**: `scrub_before_posting()` strips bare URLs, @-mentions, and secret-shaped strings, and caps length, before any model-generated text reaches a GitHub API call.
- **Suggest-only, nothing auto-merges.** The check run is advisory (`neutral`/`success`, never a hard failure by default); fixes are inline `suggestion` blocks a human applies.
- **Least-privilege GitHub App token**, minted per installation and cached with an early-refresh margin; it's held only by `GitHubClient`, never passed to the scanner or the LLM.

## Project structure

```
src/prreviewer/
├── app.py                    # FastAPI webhook gateway
├── config.py                 # Settings (env-driven)
├── diffing.py                # Unified diff → changed-line map
├── findings.py                # Finding/Category/Severity model + merge
├── sanitize.py                # Prompt-injection hardening, output scrubbing
├── queue.py                   # ARQ enqueue helper
├── worker.py                  # run_review: the end-to-end pipeline
├── github/
│   ├── auth.py                # App JWT → installation token, cached
│   ├── client.py               # PR diff/files/content, check runs, reviews
│   └── signature.py            # Webhook HMAC verification
├── llm/
│   ├── client.py               # OpenAI-compatible chat completions wrapper
│   ├── prompts.py               # System prompt + user message builder
│   └── reviewer.py              # Per-file review orchestration
├── scanners/
│   └── semgrep_scanner.py       # Semgrep subprocess → Finding objects
└── publisher/
    ├── formatting.py            # Finding[] → GitHub Checks/Review payloads
    └── publish.py                # Posts check run + PR review

scripts/
├── run_dev.sh                  # Starts Redis + gateway + worker locally
├── dry_run.py                   # Run the full pipeline against a local git diff, print to stdout
└── simulate_webhook.py           # POST a signed fixture webhook at a running gateway

tests/                          # pytest: diffing, findings merge, formatting, LLM client, sanitize, signature
docs/SETUP.md                   # Full local setup walkthrough (GitHub App, webhook tunnel, LLM key)
ARCHITECTURE.md                 # Full multi-phase design doc (this repo implements Phase 1)
```

## Getting started

Full walkthrough (creating the GitHub App, exposing your local server for webhooks, getting an LLM key) is in [docs/SETUP.md](docs/SETUP.md). Condensed version:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install semgrep

redis-server --daemonize yes        # brew install redis if needed

cp .env.example .env
# fill in GITHUB_APP_ID, GITHUB_WEBHOOK_SECRET, LLM_API_KEY (see docs/SETUP.md)

scripts/run_dev.sh                  # gateway on :8000 + ARQ worker
```

**Fastest smoke test — no GitHub App needed:**

```bash
python scripts/dry_run.py --repo-path . --base main --head <some-branch>
```

Runs Semgrep + the LLM against a real local `git diff` and prints findings straight to stdout.

## Configuration

All settings are read from `.env` (see `.env.example`) via `config.py`:

| Variable | Default | Purpose |
|---|---|---|
| `GITHUB_APP_ID` | — | GitHub App ID, used to sign the auth JWT. |
| `GITHUB_APP_PRIVATE_KEY_PATH` | `./github-app-private-key.pem` | Path to the App's downloaded private key. |
| `GITHUB_WEBHOOK_SECRET` | — | Shared secret for verifying `X-Hub-Signature-256`. |
| `LLM_API_KEY` | — | Key for the LLM endpoint. |
| `LLM_BASE_URL` | `https://openrouter.ai/api/v1` | Any OpenAI-compatible chat completions host. |
| `LLM_MODEL` | `z-ai/glm-5.2:free` | Model name passed to that endpoint. |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection for the ARQ queue. |
| `MAX_FILES_PER_PR` | `40` | Caps how many changed files are reviewed per PR. |
| `MAX_FILE_BYTES` | `200000` | Files larger than this are skipped. |
| `SKIP_BOT_AUTHORS` | `true` | Drops webhooks where the PR author's login ends in `[bot]`. |

`.env` is git-ignored — never commit it. Treat any credential that has ever been committed as compromised and rotate it.

## Testing

```bash
pytest
```

Covers diff parsing, finding merge/dedupe, GitHub-Copilot-style formatting output, the LLM client, the sanitizer, and webhook signature verification. Fixtures for a sample diff, Semgrep output, and a webhook payload live in `tests/fixtures/`.

## Known limitations

- Semgrep runs as a plain subprocess against downloaded file contents in a temp directory — not a sandboxed/isolated container. Fine for self-reviewed repos; not yet safe for scanning arbitrary third-party fork PRs.
- No Postgres or dashboard yet — results only surface in GitHub's own check-run and review UI, and nothing is persisted between runs beyond the "latest SHA" marker in Redis.
- No auto-opened "fix PR" for multi-file fixes — only inline `suggestion` comments the author applies manually to single-hunk fixes.
- Dead-code and missing-test-coverage findings are best-effort (diff + filename heuristics), not whole-program analysis.
- Free-tier LLM models (e.g. the default OpenRouter model) are rate-limited; when a call fails, that file's LLM findings are skipped and Semgrep's findings still post — the PR is never left unreviewed because of it.

## Roadmap

This repo implements **Phase 1 (Reviewer MVP)** of the design in [ARCHITECTURE.md](ARCHITECTURE.md). Later phases, not yet built:

| Phase | Name | Adds |
|---|---|---|
| 2 | LLM triage | A dedicated true/false-positive judgment call per finding, with cited evidence; an eval set for measuring precision. |
| 3 | Autofix | A validated patch-writing call — apply, re-parse, re-run the same rule, lint, test — plus an "Open fix PR" flow for multi-file fixes. |
| 4 | Dashboard | Postgres-backed history, trends, per-repo settings, and dismissal feedback ("memories") that inform future triage. |
