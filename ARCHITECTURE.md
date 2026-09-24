# Autonomous PR Security Reviewer: Architecture Blueprint

> Status: proposed design, v1 (24 Sep 2026). Research and design only; no code written yet.
> Online version with diagram: https://claude.ai/artifact/VXGFDwXKxTa7YzEqnbfCMC

A GitHub App that reads each pull request, flags OWASP Top 10 issues on the lines that changed, and proposes fixes a human applies in one click. Static analysis finds candidates, the LLM judges and patches them, and nothing merges without a person.

**Stack:** FastAPI, Postgres, Redis queue, Semgrep + LLM, React dashboard.

---

## How to continue this work locally

1. Create a new repo and put this file in it as `docs/ARCHITECTURE.md`.
2. Open Claude Code in that folder and start with a prompt like:

   > Read docs/ARCHITECTURE.md. It is the agreed design for this project. Scaffold Phase 1 (Reviewer MVP) as described: a FastAPI GitHub App webhook gateway, a Redis job queue, a worker that runs Semgrep on the PR diff, and a publisher that posts a check run and inline review comments. Python 3.12, one language target (Python code) to start.

3. Optionally add a `CLAUDE.md` that says "Follow docs/ARCHITECTURE.md; the Security section is non-negotiable" so every session picks it up.

---

## 1. Decisions at a glance

| # | Question | Recommendation |
|---|----------|----------------|
| 1 | Patch trust model | **Suggest-only with one-click apply.** Inline `suggestion` blocks, plus a human-triggered "Open fix PR". No auto-merge, ever. |
| 2 | LLM choice | **Hosted reasoning-grade API by default, behind a provider interface.** CodeLlama is dated; use a current open-weight coder (Qwen3-Coder, DeepSeek, GLM) for on-prem. |
| 3 | Scan scope | **Diff-anchored reporting, repo-aware analysis.** Report only on changed lines, but analyze whole touched files plus callers and callees. Nightly full-repo baseline. |
| 4 | Hosting | **FastAPI GitHub App + sandboxed worker pool.** GitHub Action variant later for self-hosters. |

---

## 2. Patterns borrowed from existing tools

| Tool | How it works | What to reuse |
|------|--------------|---------------|
| GitHub Copilot Autofix | CodeQL finds the alert first. The LLM gets the alert, CodeQL help text and code snippets along the taint flow path, and returns before/after edits. Fixes are parsed, type-checked and re-scanned before being shown. | Detector first, LLM second. Before/after edit format (not raw diffs). Fix must remove the alert and add no new alert. |
| Semgrep Assistant | Rules find candidates; AI triages with an explanation and hides likely false positives. "Memories" store team triage decisions and preferred sanitizers. | A triage stage that can suppress noise. Dismissals become per-repo guidance. Confidence threshold for showing fixes. |
| CodeQL / GHAS | SARIF upload; check annotations and PR alerts only for code the PR introduced. | Diff-aware reporting. SARIF as the internal finding format. |
| Snyk Code, CodeGuru | PR checks with inline comments; fixes proposed, not pushed. | Inline comments on the exact line with severity, CWE and a details link. |

Research support: the ZeroFalse study (arXiv 2510.02534) fed CodeQL alerts enriched with dataflow traces and small per-CWE rubrics to LLMs and reached precision above 0.97 on the OWASP Benchmark. Well-structured context beat a bigger context window, and reasoning-oriented models generalized best to real projects.

---

## 3. Components

| Component | Responsibility |
|-----------|----------------|
| Webhook gateway (FastAPI) | Verify `X-Hub-Signature-256`, filter events, enqueue, return 202 within GitHub's 10 s window. Stateless. |
| Job queue (Redis, ARQ or Celery) | One job per repo + head SHA; a newer push cancels the older scan. |
| Workspace builder | Mint short-lived installation token (contents: read), shallow-clone head SHA, fetch unified diff. Token never enters the scan container. |
| Static scanners (sandbox) | Semgrep (OWASP + language rulesets + custom rules), gitleaks (secrets), OSV-Scanner (dependencies). Output normalized to SARIF. |
| Context builder + diff filter | Keep findings on changed lines or newly reachable sinks. Attach enclosing function, callers/callees (tree-sitter), taint path, framework hints, past dismissals. |
| LLM service | Three calls (A, B, C below). No tools, no credentials. JSON-schema output only. |
| Patch validator (sandbox) | Apply edit, re-parse, re-run same Semgrep rule, lint, run tests (same-repo PRs only, no network). |
| Publisher | Fill fixed templates from validated JSON. Post check run + one PR review. |
| Postgres + React dashboard | Scans, findings, verdicts, feedback, per-repo settings, "Open fix PR" button, trends. |

---

## 4. End-to-end flow

1. **Webhook arrives.** `pull_request` (opened, synchronize, reopened, ready_for_review). Gateway verifies HMAC, drops drafts and bot authors per repo settings, returns 202.
2. **Job is queued.** Keyed on repo + head SHA. A check run is created immediately as "in progress".
3. **Workspace is built.** Worker mints a read-only installation token, shallow-clones the head SHA into an ephemeral container, fetches the diff.
4. **Static scanners run.** Semgrep, gitleaks, OSV-Scanner, all to SARIF.
5. **Findings are filtered and enriched.** Keep findings on added/modified lines, or on unchanged sinks a changed line now reaches. Attach context for each.
6. **LLM judges.** Call A reviews each hunk for logic flaws rules cannot see. Call B decides true/false positive for every finding. Only high-severity, high-confidence findings go to call C for a patch.
7. **Patch is validated.** Apply before/after edit, re-parse, re-run the same rule (must go quiet, no new rule may fire), lint, run tests where allowed. Failed patch is dropped; finding posts without a fix.
8. **Result is assembled.** Publisher fills fixed templates. Model prose is length-capped and scrubbed for secrets, links and @-mentions.
9. **Result is posted.** Check run completes with summary and annotations (batched 50 per request, the Checks API limit). One PR review with inline comments; a `suggestion` block when the fix is a single contiguous hunk. Everything stored for the dashboard.

```
GitHub ──webhook──> Gateway ──> Queue ──> [SANDBOX: clone → scanners → context builder]
                                                          │
                                                          v
                                   LLM service (A diff review, B triage, C patch)
                                                          │
                                                          v
                          [SANDBOX: patch validator] ──> Publisher ──> GitHub (check run + review)
                                                          │
                                                          v
                                               Postgres + React dashboard
```

---

## 5. How static and LLM analysis combine

**Stage 1: Detect.** Rules give cheap, deterministic, high-recall candidates (injection, XSS, secrets, weak crypto, vulnerable deps). LLM call A covers what rules miss: new routes without auth checks, object lookups without owner checks (IDOR), permissive CORS changes.

**Stage 2: Triage.** LLM call B sees one finding with its taint path, sanitizers in scope and a 10 to 20 line rubric for that CWE. It must cite the exact lines proving exploitability. No citation means drop or mark low confidence.

**Stage 3: Fix.** LLM call C writes a minimal before/after edit plus an explanation. The validator is the gate: a patch that does not silence the rule, breaks parsing, or touches lines outside the finding's region is discarded.

### LLM calls

| Call | Context sent | Output (schema-enforced) |
|------|--------------|--------------------------|
| A: Diff reviewer | One hunk, full surrounding function, route/handler signature, auth middleware in use. Chunk by function, never mid-function; batch large PRs per file. | `findings[]`: file, line range, OWASP category, CWE, severity, evidence lines, confidence |
| B: Triage judge | One finding, source-to-sink snippets, nearby sanitizers/validators, CWE rubric, repo memories from past dismissals. | `verdict` (true_positive / false_positive / needs_human), reasoning, cited lines, confidence 0–1 |
| C: Patch writer | Confirmed finding, editable region with line numbers, imports, project's existing safe helpers. | `edits[]` as before/after blocks, new dependencies (checked against registry), explanation |

Example finding record:

```json
{
  "file": "api/orders.py", "start_line": 42, "end_line": 44,
  "owasp": "A05:2025 Injection", "cwe": "CWE-89", "severity": "high",
  "verdict": "true_positive", "confidence": 0.91,
  "evidence": ["api/orders.py:42 f-string builds SQL from request.args['id']"],
  "patch": {
    "before": "cur.execute(f\"SELECT * FROM orders WHERE id={oid}\")",
    "after":  "cur.execute(\"SELECT * FROM orders WHERE id=%s\", (oid,))"
  }
}
```

### OWASP Top 10 (2025) coverage

| Category | Primary detector | Notes |
|----------|------------------|-------|
| A01 Broken Access Control | LLM | Missing auth decorators, IDOR, path traversal. Biggest LLM win. |
| A02 Security Misconfiguration | Both | Debug flags, CORS `*`, IaC (Checkov can be added). |
| A03 Software Supply Chain Failures | Static | OSV-Scanner on lockfile changes; LLM explains the upgrade. |
| A04 Cryptographic Failures | Static | Weak hashes, hard-coded keys, disabled TLS verification. |
| A05 Injection | Both | SQL, command, template, XSS. Rules find, LLM confirms taint path. |
| A06 Insecure Design | LLM | Advisory only, no auto-patch. |
| A07 Authentication Failures | Both | JWT `verify=False`, weak session config, password handling. |
| A08 Software or Data Integrity Failures | Static | Unsafe deserialization (`pickle`, `yaml.load`), unsigned updates. |
| A09 Logging & Alerting Failures | LLM | Secrets/PII in logs, unlogged auth failures. |
| A10 Mishandling of Exceptional Conditions | Both | Fail-open `except` blocks, stack traces returned to clients. |

---

## 6. Security of the reviewer itself (non-negotiable)

The PR is attacker-controlled input. In 2026 researchers ("Comment and Control", Cloud Security Alliance) showed prompt injection in PR titles, issue bodies and hidden HTML comments turning three vendors' GitHub AI agents into credential exfiltrators.

- **LLM has no hands.** No tool calls, shell, network or credentials in any LLM context. It returns JSON that plain code validates and acts on.
- **Untrusted data is fenced.** Code goes in delimited blocks marked as data. PR title, body and commit messages are not sent. HTML comments and invisible Unicode (bidi, zero-width) are stripped, and their presence is itself a finding.
- **Output is templated.** The bot never posts free-form model text. Fields are length-capped and scanned for secrets, URLs and @-mentions before posting.
- **Suppression is suspicious.** An injection's likeliest goal is "report nothing". A static finding can be downgraded by the LLM but never silently deleted; it stays in the dashboard with the verdict.
- **PR code never runs with secrets.** Running tests executes attacker code. Tests run only for same-repo PRs, in a container with no network and no tokens. Fork PRs get scanning only.
- **Least-privilege App.** Contents: read; pull requests: write; checks: write. Contents: write only for the opt-in "Open fix PR" path, via a separate token minted per click.
- **Patches stay in their lane.** A patch may touch only lines inside the finding's region, may not edit CI files, lockfiles or the bot's own config; new dependencies are checked against the registry.

---

## 7. Design decisions in detail

### 7.1 Patch trust model: suggest-only, one-click apply

Every shipping autofix tool still makes a human commit the fix. LLM-found vulnerabilities have real false-positive rates, and a wrong "security fix" that silently changes behavior is worse than none. An auto-opening agent is also a bigger target: an injection that steers the patch writer becomes a commit.

- Single-hunk fix: inline review comment with a `suggestion` block, committed by the author in one click.
- Multi-file fix: "Open fix PR" button in the dashboard, targeting the author's branch, not main.
- Later: per-repo auto-open for deterministic rule classes with a proven acceptance rate.

### 7.2 LLM choice: hosted reasoning model, pluggable

Triage accuracy is the product, and reasoning models do it markedly better. CodeLlama (2023) trails current open-weight coders, so self-hosting should use one of those. Cost stays bounded because the LLM sees findings and hunks, not whole repos; prompt caching of the static system prompt and rubrics cuts it further.

- Code leaving the network: use providers' zero-data-retention terms. Customers who refuse get self-hosted (vLLM on their GPUs).
- Different models per call: cheaper for A, strongest for B and C.
- Keep a labeled eval set (OWASP Benchmark + your own triaged PRs) so model swaps are measured.

### 7.3 Scan scope: diff-anchored, repo-aware

Diff-only misses a new call into existing vulnerable code. Full-repo reporting buries authors in issues they didn't cause. Analyze with full context, report only what this PR introduces or newly reaches.

- Scanners run on full touched files; context builder pulls callers/callees repo-wide.
- Post a finding if it sits on a changed line, or a changed line creates a new path into an existing sink.
- Full-repo baseline on install and nightly; pre-existing findings live in the dashboard, not on PRs.

### 7.4 Hosting: FastAPI GitHub App + sandboxed workers

A dashboard, cross-PR memory, per-repo settings and a feedback loop need a stateful service. A GitHub App gets its own bot identity and per-installation tokens instead of PATs. A GitHub Action can come later, calling the same analysis core as a CLI.

- Gateway: FastAPI, stateless, verify and enqueue only.
- Workers: Python (ARQ or Celery) in throwaway containers (gVisor or Firecracker when hosting other people's code).
- Store: Postgres for scans/findings/feedback; object storage for SARIF and logs.

---

## 8. Build phases

| Phase | Name | Scope |
|-------|------|-------|
| 1 | Reviewer MVP | GitHub App + webhook gateway; Semgrep on diff + diff filter; check run + inline comments; one language (Python or JS) |
| 2 | LLM triage | Context builder; calls A and B; eval set + precision tracking; injection hardening |
| 3 | Autofix | Call C + validator; `suggestion` blocks; Open-fix-PR flow |
| 4 | Dashboard | React: scans, findings, trends; dismissal feedback as memories; per-repo rules and thresholds |

---

## Sources

- GitHub Blog, Fixing security vulnerabilities with AI: https://github.blog/engineering/platform-security/fixing-security-vulnerabilities-with-ai/
- GitHub Docs, About Copilot Autofix: https://docs.github.com/en/code-security/concepts/code-scanning/copilot-autofix-for-code-scanning
- Semgrep Docs, AI triage and autofix: https://docs.semgrep.dev/semgrep-multimodal/overview.md
- Semgrep, AI noise filtering and triage memories: https://semgrep.dev/blog/2025/announcing-ai-noise-filtering-and-triage-memories/
- ZeroFalse (arXiv 2510.02534): https://arxiv.org/html/2510.02534
- Sifting the Noise (arXiv 2601.22952): https://arxiv.org/html/2601.22952v1
- CSA, Comment and Control: https://labs.cloudsecurityalliance.org/research/csa-research-note-comment-control-github-prompt-injection-20/
- GitHub Docs, Pull request reviews API: https://docs.github.com/en/rest/pulls/reviews
- GitHub Docs, Review comments API: https://docs.github.com/en/rest/pulls/comments
- GitHub Community, Checks API 50-annotation limit: https://github.com/orgs/community/discussions/26680
