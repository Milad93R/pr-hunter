from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

from pr_hunter.config import AIProfile


class AIReviewError(RuntimeError):
    """The optional AI review could not be completed."""


def _endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _extract_json(content: str) -> dict[str, Any]:
    stripped = content.strip()
    fenced = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL | re.IGNORECASE
    )
    if fenced:
        stripped = fenced.group(1).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise AIReviewError("Model did not return a JSON object")
        try:
            value = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as error:
            raise AIReviewError("Model returned invalid JSON") from error
    if not isinstance(value, dict):
        raise AIReviewError("Model returned JSON that is not an object")
    return value


def _chat(profile: AIProfile, messages: list[dict[str, str]]) -> dict[str, Any]:
    key = os.environ.get(profile.api_key_env)
    if not key:
        raise AIReviewError(f"Missing environment variable: {profile.api_key_env}")
    payload = json.dumps(
        {
            "model": profile.model,
            "messages": messages,
            "max_tokens": 1600,
            "temperature": 0.1,
        }
    ).encode()
    request = urllib.request.Request(
        _endpoint(profile.base_url),
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "pr-hunter/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise AIReviewError(
            f"AI endpoint returned HTTP {error.code}: {body[:500]}"
        ) from error
    except urllib.error.URLError as error:
        raise AIReviewError(f"AI endpoint failed: {error.reason}") from error
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise AIReviewError("Unexpected chat-completions response") from error
    if isinstance(content, list):
        content = "".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    return _extract_json(str(content))


def two_account_review(
    candidate_record: dict[str, Any],
    scout: AIProfile,
    reviewer: AIProfile,
) -> dict[str, Any]:
    snapshot = candidate_record["snapshot"]
    candidate = snapshot["candidate"]
    candidate["body"] = (candidate.get("body") or "")[:8_000]
    evidence = json.dumps(snapshot, indent=2, ensure_ascii=False)
    scout_prompt = f"""
You are the scout for an open-source contribution decision. Evaluate the
candidate evidence below. Distinguish facts from assumptions. You have not
cloned the repository and must never claim the issue was reproduced or that a
root cause is proven.

Return JSON only with these keys:
recommendation (strong|investigate|skip), fit_reason, likely_scope
(small|medium|large|unknown), estimated_hours (number or null),
root_cause_status (unknown|hypothesis_only), maintainer_signal,
career_value (low|medium|high), risks (array), investigation_steps (array),
maintainer_questions (array).

Evidence:
{evidence}
""".strip()
    scout_result = _chat(
        scout,
        [
            {
                "role": "system",
                "content": "Be evidence-bound, concise, and skeptical.",
            },
            {"role": "user", "content": scout_prompt},
        ],
    )

    reviewer_prompt = f"""
You are the skeptical maintainer-side reviewer. Try to reject the scout's
recommendation when evidence is weak. Focus on unproven root cause, competing
work, maintainer interest, likely scope expansion, test feasibility, and
career value per hour. Do not invent repository facts.

Return JSON only with these keys:
verdict (agree|downgrade|veto), final_recommendation
(strong|investigate|skip), decisive_reason, unsupported_claims (array),
missing_evidence (array), stop_conditions (array), safest_next_action.

Candidate evidence:
{evidence}

Scout analysis:
{json.dumps(scout_result, indent=2, ensure_ascii=False)}
""".strip()
    reviewer_result = _chat(
        reviewer,
        [
            {
                "role": "system",
                "content": "Act as an adversarial reviewer, not a collaborator.",
            },
            {"role": "user", "content": reviewer_prompt},
        ],
    )
    return {
        "candidate_key": candidate_record["candidate_key"],
        "reviewed_at": datetime.now(UTC).isoformat(),
        "scout": scout_result,
        "reviewer": reviewer_result,
    }
