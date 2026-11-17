"""What the meeting graders share: reading a "prepare and follow up" answer, the follow-up criterion, and the
assembly of the grade with the CRM sandbox's diff and the tone jury's votes.

A meeting grader (T-MTG-01 to 04) scores the answer's own criteria (output parses, the finding and the
amounts it turns on), then adds:

- follow-up (20): the run added to the task's household a note recording what was discussed, which states
  the key's note amount (within a dollar), and at least one activity for an open item;
- tone (15): `graders.follow_up.tone_criterion`, essential only when a vote is missing.

The critical fails, in order: `graders.follow_up.critical` (another household's write, an account number in
an external message), then the fabricated-figure rule over the answer, then over the text of the run's own
CRM records (a figure made up in a note is as fabricated as one in the answer).
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from casebook.graders.common import (
    OUTPUT_PARSES,
    TOLERANCE,
    Figure,
    Grade,
    NotMoney,
    Support,
    close,
    figures,
    grade_from,
    json_block,
    money,
)
from casebook.graders.follow_up import CLIENT_MESSAGE, TONE, FollowUp, client_message, critical, tone_criterion
from casebook.model.money import fmt, parse_decimal

FOLLOW_UP = "follow_up"
FOLLOW_UP_POINTS = 20
ADDED = "added"
NOTES, ACTIVITIES = "notes", "activities"
# The text of a CRM record: a note's, an activity's summary.
TEXT_FIELDS = ("text", "summary")
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")

type Result = tuple[str, int, bool | int, str]


@dataclass(frozen=True)
class Answer:
    """What could be read from the json block; None where a field is absent or malformed."""

    data: dict[str, Any]
    finding: str | None
    amounts: dict[str, Decimal | None]
    figures: tuple[Figure, ...]
    problems: tuple[str, ...]
    well_formed: frozenset[str]


def read_answer(
    output_text: str,
    required: Sequence[str],
    findings: Sequence[str],
    amounts: Sequence[str],
    lists: Sequence[str] = (),
) -> Answer:
    """The answer's json block: every field in `required` (the client message included) present, the finding
    one of `findings`, each of `amounts` money or null, each of `lists` a list, the figures well formed, the
    client message text."""
    data = json_block(output_text)
    if isinstance(data, str):
        return Answer({}, None, dict.fromkeys(amounts), (), (data,), frozenset())
    problems = [f"lacks {name}" for name in required if name not in data]
    finding = data.get("finding")
    if "finding" in data and finding not in findings:
        problems.append(f"finding {finding!r} is not one of {', '.join(findings)}")
        finding = None
    well_formed = {name for name in required if name in data}
    read: dict[str, Decimal | None] = {}
    for name in amounts:
        try:
            read[name] = money(data.get(name))
        except NotMoney:
            problems.append(f"{name} {data[name]!r} is not money")
            well_formed.discard(name)
            read[name] = None
    for name in lists:
        if name in data and not isinstance(data[name], list):
            problems.append(f"{name} is not a list")
    if "explanation" in data and not isinstance(data["explanation"], str):
        problems.append("explanation is not text")
    if CLIENT_MESSAGE in data and not isinstance(data[CLIENT_MESSAGE], str):
        problems.append("client_message is not text")
    elif CLIENT_MESSAGE in data and client_message(output_text) is None:
        problems.append("client_message is empty")
    cited = figures(data["figures"], problems) if "figures" in data else ()
    return Answer(
        data=data,
        finding=str(finding) if finding is not None else None,
        amounts=read,
        figures=cited,
        problems=tuple(problems),
        well_formed=frozenset(well_formed),
    )


def output_parses(answer: Answer) -> Result:
    return (OUTPUT_PARSES, 10, not answer.problems, "; ".join(answer.problems) or "every required field present")


def amount_result(name: str, points: int, answer: Answer, expected: Decimal, null_ok: bool) -> Result:
    """An amount within a dollar of the key's; where the key's is zero, `null_ok` accepts null for it too."""
    value = answer.amounts.get(name)
    if null_ok and expected == 0:
        met = name in answer.well_formed and (value is None or close(value, expected))
        rule = f"0 or null (key {fmt(expected)})"
    else:
        met = close(value, expected)
        rule = f"within {fmt(TOLERANCE)} of {fmt(expected)}"
    return (name, points, met, f"answer {'none' if value is None else fmt(value)}, needs {rule}")


def _texts(follow_up: FollowUp) -> list[tuple[str, str]]:
    """Each record the run added or changed in the task's household, with its text (a note's, an activity's
    summary)."""
    found: list[tuple[str, str]] = []
    for change in follow_up.own:
        if change.after is None:
            continue
        text = " ".join(str(change.after[f]) for f in TEXT_FIELDS if f in change.after)
        found.append((f"{change.collection} {change.record_id}", text))
    return found


def _states(text: str, amount: Decimal) -> bool:
    return any(close(parse_decimal(n.replace(",", "")), amount) for n in _NUMBER.findall(text))


def follow_up_result(follow_up: FollowUp, note_amount: Decimal, about: str) -> Result:
    """A note that states `note_amount` (what the key turns on) and at least one activity, both added to the
    task's household."""
    added = [c for c in follow_up.own if c.change == ADDED and c.after is not None]
    notes = [c for c in added if c.collection == NOTES]
    stating = [c for c in notes if _states(str(c.after.get("text", "")) if c.after else "", note_amount)]
    activities = [c for c in added if c.collection == ACTIVITIES]
    lacks = []
    if not notes:
        lacks.append(f"no note added to {follow_up.household_id}")
    elif not stating:
        lacks.append(f"no note added states {about}, {fmt(note_amount)}")
    if not activities:
        lacks.append(f"no activity added to {follow_up.household_id} for an open item")
    detail = "; ".join(lacks) or (
        f"note {stating[0].record_id} states {about}; activities {', '.join(c.record_id for c in activities)}"
    )
    return (FOLLOW_UP, FOLLOW_UP_POINTS, not lacks, detail)


def _critical(
    output_text: str,
    answer: Answer,
    headline: Sequence[tuple[str, Decimal | None]],
    computed: Iterable[Decimal],
    fixtures: Path,
    follow_up: FollowUp,
) -> str | None:
    shared = critical(output_text, follow_up)
    if shared is not None:
        return shared
    support = Support(fixtures, list(computed))
    fabricated = support.first_fabrication(output_text, answer.figures, headline)
    if fabricated is not None:
        return fabricated
    for where, text in _texts(follow_up):
        in_crm = support.first_fabrication(text, (), ())
        if in_crm is not None:
            return f"in the CRM, {where}: {in_crm}"
    return None


def grade_meeting(
    output_text: str,
    answer: Answer,
    results: Sequence[Result],
    essential: Sequence[str],
    counts: dict[str, int],
    headline: Sequence[tuple[str, Decimal | None]],
    computed: Iterable[Decimal],
    fixtures: Path,
    follow_up: FollowUp,
    note: tuple[Decimal, str],
) -> Grade:
    """The grade from the answer's own criteria, the follow-up and the tone; `note` is the amount the note
    must state and what it is."""
    # With no client message there is nothing the jury could have scored.
    tone, tone_essential = tone_criterion(follow_up.tone if client_message(output_text) is not None else None)
    all_results = [*results, follow_up_result(follow_up, *note), tone]
    critical_fail = _critical(output_text, answer, headline, computed, fixtures, follow_up)
    return grade_from(all_results, critical_fail, counts, (*essential, TONE) if tone_essential else essential)
