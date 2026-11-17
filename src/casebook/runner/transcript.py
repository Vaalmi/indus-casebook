"""Read the CLI's stream-json transcript: the result, the models, the tokens, the instruction."""

import json
import re
from dataclasses import dataclass, field
from typing import Any

# The failure reason of a quota stop: a pass pauses on it, and a run stops retrying.
QUOTA_REASON = "quota"
QUOTA = re.compile(r"usage limit|rate limit|hit your limit|quota", re.IGNORECASE)


@dataclass(frozen=True)
class Transcript:
    events: list[dict[str, Any]]
    result: dict[str, Any] | None
    init: dict[str, Any] | None
    skills_invoked: list[str] = field(default_factory=lambda: list[str]())

    @property
    def reported_models(self) -> list[str]:
        models: list[str] = []
        if self.init and self.init.get("model"):
            models.append(str(self.init["model"]))
        if self.result:
            models += [str(m) for m in (self.result.get("modelUsage") or {}) if str(m) not in models]
        return models

    @property
    def token_use(self) -> dict[str, int]:
        usage = (self.result or {}).get("usage") or {}
        return {k: int(v) for k, v in usage.items() if isinstance(v, int)}

    @property
    def final_text(self) -> str:
        return str((self.result or {}).get("result") or "")


def parse_transcript(stdout: str) -> Transcript:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            events.append({"type": "unparsed", "text": line})
            continue
        if isinstance(event, dict):
            events.append(event)
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)
    results = {
        block.get("tool_use_id"): bool(block.get("is_error"))
        for e in events
        if e.get("type") == "user"
        for block in (e.get("message") or {}).get("content") or []
        if isinstance(block, dict) and block.get("type") == "tool_result"
    }
    # A skill counts as loaded only when its call has a result and the result is not an error.
    skills = [
        str((block.get("input") or {}).get("skill", ""))
        for e in events
        if e.get("type") == "assistant"
        for block in (e.get("message") or {}).get("content") or []
        if isinstance(block, dict)
        and block.get("type") == "tool_use"
        and block.get("name") == "Skill"
        and results.get(block.get("id")) is False
    ]
    return Transcript(events, result, init, skills)


def failure_reason(exit_code: int | None, timed_out: bool, transcript: Transcript, stderr: str) -> str | None:
    """Why a run failed, or None. Judged by is_error and the exit code, never by subtype."""
    if timed_out:
        return "timeout"
    result = transcript.result
    text = transcript.final_text + " " + stderr
    if result is None:
        return QUOTA_REASON if QUOTA.search(text) else f"no result from the CLI (exit code {exit_code})"
    if result.get("is_error") or exit_code != 0:
        return (
            QUOTA_REASON if QUOTA.search(text) else f"CLI error (exit code {exit_code}): {transcript.final_text[:300]}"
        )
    return None
