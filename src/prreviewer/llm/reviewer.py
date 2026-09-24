"""Orchestrates one LLM review call per changed file: sanitize input, prompt,
parse+validate the JSON response, retry once on failure, degrade gracefully
(skip this file's LLM findings, keep Semgrep's) rather than fail the PR.
"""

import json
import logging
import re

from pydantic import BaseModel, ValidationError

from ..diffing import FileDiff
from ..findings import Category, Finding, Severity
from ..sanitize import sanitize_for_llm
from .client import LLMClient
from .prompts import RETRY_SUFFIX, SYSTEM_PROMPT, build_user_message

logger = logging.getLogger(__name__)

SUGGESTION_CONFIDENCE_THRESHOLD = 0.6
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


class _RawFindingItem(BaseModel):
    start_line: int
    end_line: int
    category: Category
    severity: Severity
    message: str
    owasp: str | None = None
    cwe: str | None = None
    suggestion: str | None = None
    confidence: float = 0.5


class _RawResponse(BaseModel):
    findings: list[_RawFindingItem] = []


def _extract_json(raw: str) -> dict:
    fenced = _JSON_FENCE_RE.search(raw)
    candidate = fenced.group(1) if fenced else raw
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise json.JSONDecodeError("no JSON object found", candidate, 0)
    return json.loads(candidate[start : end + 1])


async def review_file(
    client: LLMClient,
    file_path: str,
    file_diff: FileDiff,
    diff_text: str,
    file_context: str,
    missing_test_hint: str | None = None,
) -> list[Finding]:
    sanitize_findings: list[Finding] = []

    clean_diff, diff_flag = sanitize_for_llm(file_path, diff_text)
    if diff_flag:
        sanitize_findings.append(diff_flag)
    clean_context, context_flag = sanitize_for_llm(file_path, file_context)
    if context_flag:
        sanitize_findings.append(context_flag)

    user_message = build_user_message(file_path, clean_diff, clean_context, missing_test_hint)

    raw_response = await _call_with_retry(client, user_message)
    if raw_response is None:
        return sanitize_findings

    findings = [
        Finding(
            file=file_path,
            start_line=item.start_line,
            end_line=item.end_line,
            category=item.category,
            severity=item.severity,
            message=item.message,
            source="llm",
            owasp=item.owasp,
            cwe=item.cwe,
            suggestion=item.suggestion if item.confidence >= SUGGESTION_CONFIDENCE_THRESHOLD else None,
            confidence=item.confidence,
        )
        for item in raw_response.findings
        if file_diff.overlaps_changed_range(item.start_line, item.end_line)
    ]
    return sanitize_findings + findings


async def _call_with_retry(client: LLMClient, user_message: str) -> _RawResponse | None:
    system_prompt = SYSTEM_PROMPT
    for attempt in range(2):
        try:
            raw = await client.complete(system_prompt, user_message)
            data = _extract_json(raw)
            return _RawResponse.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            if attempt == 0:
                system_prompt = SYSTEM_PROMPT + RETRY_SUFFIX.format(error=str(exc))
                continue
            logger.warning("LLM response failed validation twice, skipping LLM findings: %s", exc)
            return None
        except Exception:
            logger.exception("LLM call failed, skipping LLM findings for this file")
            return None
    return None
