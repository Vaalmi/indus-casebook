"""What every compliance grader shares: the expected output's schema rule, the issues for reviewer attention,
and the book-level lists.

A compliance answer is written for the firm's chief compliance officer by an adviser that is not a law firm:
it raises issues for a reviewer and draws no legal conclusion. So a compliance task's expected output has an
"issues_for_reviewer" field and none whose name says it holds a legal conclusion, a violation, a ruling, a
breach determination or a compliant or non-compliant verdict: `tasks.schemas` refuses such a task file when
it loads.

Each issue for reviewer attention is an object naming the records it rests on by their IDs, what the records
show, and why the reviewer should look. An issue the key expects is named when one entry names every record
the key lists for it, anywhere in the entry.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from casebook.graders import household_list
from casebook.graders.common import OUTPUT_PARSES, Grade, grade_from, json_block
from casebook.keys.issues import Issue
from casebook.tasks.schemas import ISSUES_FOR_REVIEWER

ISSUE_FIELDS = ("issue", "records", "what_the_records_show", "why_the_reviewer_should_look")
ISSUES_NAMED = "issues_named"


@dataclass(frozen=True)
class ReviewerIssues:
    """The answer's issues for reviewer attention, each entry as text, or None where the field is unreadable."""

    entries: tuple[str, ...] | None


def reviewer_issues(data: dict[str, Any], problems: list[str]) -> ReviewerIssues:
    """The answer's "issues_for_reviewer" list; each malformed entry adds a problem and is left out."""
    if ISSUES_FOR_REVIEWER not in data:
        return ReviewerIssues(None)
    raw = data[ISSUES_FOR_REVIEWER]
    if not isinstance(raw, list):
        problems.append(f"{ISSUES_FOR_REVIEWER} is not a list")
        return ReviewerIssues(None)
    entries: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or any(f not in item for f in ISSUE_FIELDS):
            problems.append(f"{ISSUES_FOR_REVIEWER}[{index}] lacks one of {', '.join(ISSUE_FIELDS)}")
            continue
        if not isinstance(item["records"], list):
            problems.append(f"{ISSUES_FOR_REVIEWER}[{index}] records is not a list")
            continue
        entries.append(json.dumps(item, default=str))
    return ReviewerIssues(tuple(entries))


def issues_result(answer: ReviewerIssues, expected: Sequence[Issue], points: int) -> tuple[str, int, bool, str]:
    """The issues criterion: every issue the key expects is named by its records in one entry."""
    if answer.entries is None:
        return (ISSUES_NAMED, points, False, f"no readable {ISSUES_FOR_REVIEWER}")
    entries = answer.entries
    missing = [i for i in expected if not any(all(r in entry for r in i.records) for entry in entries)]
    detail = "; ".join(f"{i.name}: no entry names {', '.join(i.records)}" for i in missing)
    if not detail:
        detail = f"every issue the key expects is named ({len(expected)})" if expected else "the key expects no issue"
    return (ISSUES_NAMED, points, not missing, detail)


def grade_household_list(output_text: str, key: household_list.HouseholdListKey, fixtures: Path) -> Grade:
    """A book-level compliance answer: `graders.household_list`'s grade, its output parsing only when the
    answer also has a readable "issues_for_reviewer" list."""
    graded = household_list.grade(output_text, key, fixtures)
    data = json_block(output_text)
    problems: list[str] = []
    if isinstance(data, dict):
        if ISSUES_FOR_REVIEWER not in data:
            problems.append(f"lacks {ISSUES_FOR_REVIEWER}")
        reviewer_issues(data, problems)
    results: list[tuple[str, int, bool, str]] = []
    for c in graded.breakdown:
        if c.name == OUTPUT_PARSES and problems:
            detail = "; ".join(p for p in (c.detail if c.earned < c.points else "", *problems) if p)
            results.append((c.name, c.points, False, detail))
        else:
            results.append((c.name, c.points, c.earned == c.points, c.detail))
    return grade_from(results, graded.critical_fail, graded.counts, graded.essential)
