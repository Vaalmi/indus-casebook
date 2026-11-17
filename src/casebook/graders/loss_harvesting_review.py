"""The grader for a compliance review of a household's 2025 loss harvesting across its accounts: scores an
answer's closing json block against `keys.loss_harvesting`.

- finding (30, essential): "issues_found" or "no_issues", as the key finds;
- disallowed loss (25, essential): within a dollar of the key's where a purchase replaced units of a loss sale,
  0 or null where none did;
- losses (10): the loss the custodian reports and the loss allowed, each within a dollar, whatever their sign;
- issues named (25): each issue the key expects, named in one entry of "issues_for_reviewer" by its records
  (the loss sale's transaction and each replacement purchase's);
- output parses (10).

The fabricated-figure rule and the three counts are `graders.common`'s. The key always settles the review, so
"unresolved" is an unnecessary refusal; "issues_found" where the key finds none is a false alarm.
"""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from casebook.graders.common import (
    OUTPUT_PARSES,
    TOLERANCE,
    UNRESOLVED,
    Figure,
    Grade,
    NotMoney,
    Support,
    close,
    counts_for,
    figures,
    grade_from,
    json_block,
    money,
)
from casebook.graders.compliance_review import ISSUES_FOR_REVIEWER, ReviewerIssues, issues_result, reviewer_issues
from casebook.keys.concentration_basis import ISSUES_FOUND, NO_ISSUES
from casebook.keys.loss_harvesting import LossHarvestingKey
from casebook.model.money import fmt

FINDINGS = (ISSUES_FOUND, NO_ISSUES, UNRESOLVED)
AMOUNTS = ("loss_reported", "disallowed_loss", "allowed_loss")
REQUIRED_FIELDS = ("finding", *AMOUNTS, ISSUES_FOR_REVIEWER, "figures", "explanation")

FINDING = "finding"
DISALLOWED = "disallowed"
LOSSES = "losses"
ISSUES = "issues_named"
POINTS = {OUTPUT_PARSES: 10, FINDING: 30, DISALLOWED: 25, LOSSES: 10, ISSUES: 25}


@dataclass(frozen=True)
class _Answer:
    finding: str | None
    amounts: dict[str, Decimal | None]
    # The amounts present and readable: a disallowed loss of null is an answer only where it was given.
    readable: frozenset[str]
    issues: ReviewerIssues
    figures: tuple[Figure, ...]
    problems: tuple[str, ...]


def _answer(output_text: str) -> _Answer:
    data = json_block(output_text)
    if isinstance(data, str):
        return _Answer(None, dict.fromkeys(AMOUNTS), frozenset(), ReviewerIssues(None), (), (data,))
    problems = [f"lacks {name}" for name in REQUIRED_FIELDS if name not in data]
    finding = data.get("finding")
    if "finding" in data and finding not in FINDINGS:
        problems.append(f"finding {finding!r} is not one of {', '.join(FINDINGS)}")
        finding = None
    readable = {name for name in AMOUNTS if name in data}
    amounts: dict[str, Decimal | None] = {}
    for name in AMOUNTS:
        try:
            amounts[name] = money(data.get(name))
        except NotMoney:
            problems.append(f"{name} {data[name]!r} is not money")
            readable.discard(name)
            amounts[name] = None
    if "explanation" in data and not isinstance(data["explanation"], str):
        problems.append("explanation is not text")
    issues = reviewer_issues(data, problems)
    cited = figures(data["figures"], problems) if "figures" in data else ()
    return _Answer(
        finding=str(finding) if finding is not None else None,
        amounts=amounts,
        readable=frozenset(readable),
        issues=issues,
        figures=cited,
        problems=tuple(problems),
    )


def _size(value: Decimal | None) -> Decimal | None:
    return None if value is None else abs(value)


def _shown(value: Decimal | None) -> str:
    return "none" if value is None else fmt(value)


def grade(output_text: str, key: LossHarvestingKey, fixtures: Path) -> Grade:
    answer = _answer(output_text)
    wash = key.wash_sales
    loss, disallowed, allowed = (_size(answer.amounts[name]) for name in AMOUNTS)
    if wash.washed:
        disallowed_ok = close(disallowed, wash.disallowed_loss)
        rule = f"within {fmt(TOLERANCE)} of {fmt(wash.disallowed_loss)}"
    else:
        disallowed_ok = "disallowed_loss" in answer.readable and (disallowed is None or disallowed == 0)
        rule = "0 or null"
    results = [
        (
            OUTPUT_PARSES,
            POINTS[OUTPUT_PARSES],
            not answer.problems,
            "; ".join(answer.problems) or "every required field present",
        ),
        (
            FINDING,
            POINTS[FINDING],
            answer.finding == key.finding,
            f"answer {answer.finding or 'none'}, key {key.finding}",
        ),
        (DISALLOWED, POINTS[DISALLOWED], disallowed_ok, f"answer {_shown(disallowed)}, needs {rule}"),
        (
            LOSSES,
            POINTS[LOSSES],
            close(loss, wash.loss_reported) and close(allowed, wash.allowed_loss),
            f"reported {_shown(loss)} vs {fmt(wash.loss_reported)}, "
            f"allowed {_shown(allowed)} vs {fmt(wash.allowed_loss)}",
        ),
        issues_result(answer.issues, key.issues, POINTS[ISSUES]),
    ]
    support = Support(fixtures, [f.value for f in wash.computed_figures])
    critical = support.first_fabrication(output_text, answer.figures, [(n, answer.amounts[n]) for n in AMOUNTS])
    counts = counts_for(answer.finding, key.finding, alarm=(ISSUES_FOUND,), clean=(NO_ISSUES,))
    return grade_from(results, critical, counts, essential=(FINDING, DISALLOWED))
