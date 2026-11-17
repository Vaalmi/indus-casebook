"""The expected-output schema rules a task file must meet when it loads (docs/PLAN.md, slice 10).

A compliance answer is written for the firm's chief compliance officer by an adviser that is not a law firm:
it raises issues for a reviewer and draws no legal conclusion. So a compliance task's expected output has an
"issues_for_reviewer" field and none whose name says it holds a legal conclusion, a violation, a ruling, a
breach determination or a compliant or non-compliant verdict; and its prompt states the firm's capacity, the
audience, the channel and the firm's policy (the owner's decision of 16 November 2026,
docs/decisions/2026-11-16-slice10-open-questions.md).
"""

import re
from collections.abc import Iterable

ISSUES_FOR_REVIEWER = "issues_for_reviewer"
# The words a field holding a legal conclusion is named with.
LEGAL_CONCLUSION_WORDS = frozenset(
    {
        "legal",
        "violation",
        "violations",
        "violated",
        "violates",
        "ruling",
        "rulings",
        "breach",
        "breaches",
        "breached",
        "compliant",
        "noncompliant",
        "verdict",
        "determination",
    }
)
# What every compliance prompt states, word for word: the firm's capacity, the audience, the channel, and
# the policy the task quotes after this lead-in.
COMPLIANCE_CONTEXT = {
    "firm capacity": "an SEC-registered investment adviser acting as a fiduciary; not a broker-dealer, law firm or "
    "CPA firm",
    "audience": "the firm's chief compliance officer",
    "channel": "an internal compliance memo",
    "firm policy": "The firm's policy: \"",
}


def _words(name: str) -> list[str]:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return [w.lower() for w in re.split(r"[^A-Za-z]+", spaced) if w]


def compliance_schema_problems(expected_output_fields: Iterable[str]) -> list[str]:
    """Why a compliance task's expected output is refused: a field for a legal conclusion, or no field for
    the issues a reviewer should look at."""
    fields = list(expected_output_fields)
    problems = [
        f"field {name!r} would hold a legal conclusion"
        for name in fields
        if LEGAL_CONCLUSION_WORDS & set(_words(name)) or "compliant" in name.lower()
    ]
    if ISSUES_FOR_REVIEWER not in fields:
        problems.append(f"no {ISSUES_FOR_REVIEWER!r} field")
    return problems


def compliance_prompt_problems(prompt: str) -> list[str]:
    """What of the firm's capacity, audience, channel and policy a compliance prompt does not state."""
    flat = " ".join(prompt.split())
    return [f"the prompt does not state the {what}" for what, words in COMPLIANCE_CONTEXT.items() if words not in flat]
