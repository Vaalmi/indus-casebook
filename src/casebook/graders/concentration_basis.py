"""The grader for a compliance review against the IPS and the cost basis (T-CMP-01 and T-CMP-02): scores an
answer's closing json block against `keys.concentration_basis`.

- finding (20, essential): "issues_found" or "no_issues", as the key finds;
- concentration (20, essential): the single company's stocks named above the limit are the key's, each with
  its value within a dollar;
- basis (25, essential): whether the basis can be relied on, the basis the lots still held understate and
  the gain the lots sold overstate, each within a dollar (0 or null where the key finds none);
- issues named (25): each issue the key expects, named in one entry of "issues_for_reviewer" by its records;
- output parses (10).

The fabricated-figure rule and the three counts are `graders.common`'s. The key always settles the review, so
"unresolved" is an unnecessary refusal; "issues_found" where the key finds none is a false alarm.
"""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from casebook.graders.common import (
    OUTPUT_PARSES,
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
from casebook.keys.concentration_basis import ISSUES_FOUND, NO_ISSUES, ConcentrationBasisKey
from casebook.model.money import fmt

FINDINGS = (ISSUES_FOUND, NO_ISSUES, UNRESOLVED)
ABOVE_LIMIT = "above_concentration_limit"
AMOUNTS = ("basis_understated", "gain_overstated")
REQUIRED_FIELDS = ("finding", ABOVE_LIMIT, "basis_reliable", *AMOUNTS, ISSUES_FOR_REVIEWER, "figures", "explanation")

FINDING = "finding"
CONCENTRATION = "concentration"
BASIS = "basis"
ISSUES = "issues_named"
POINTS = {OUTPUT_PARSES: 10, FINDING: 20, CONCENTRATION: 20, BASIS: 25, ISSUES: 25}


@dataclass(frozen=True)
class _Answer:
    finding: str | None
    # Each security named above the limit, with its value (None where unreadable); None if the list is unreadable.
    above_limit: dict[str, Decimal | None] | None
    basis_reliable: bool | None
    amounts: dict[str, Decimal | None]
    issues: ReviewerIssues
    figures: tuple[Figure, ...]
    problems: tuple[str, ...]


def _above_limit(raw: object, problems: list[str]) -> dict[str, Decimal | None] | None:
    if not isinstance(raw, list):
        problems.append(f"{ABOVE_LIMIT} is not a list")
        return None
    named: dict[str, Decimal | None] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or not isinstance(item.get("security_id"), str):
            problems.append(f"{ABOVE_LIMIT}[{index}] names no security_id")
            continue
        try:
            named[str(item["security_id"])] = money(item.get("value"))
        except NotMoney:
            problems.append(f"{ABOVE_LIMIT}[{index}] value {item.get('value')!r} is not money")
            named[str(item["security_id"])] = None
    return named


def _answer(output_text: str) -> _Answer:
    data = json_block(output_text)
    if isinstance(data, str):
        return _Answer(None, None, None, dict.fromkeys(AMOUNTS), ReviewerIssues(None), (), (data,))
    problems = [f"lacks {name}" for name in REQUIRED_FIELDS if name not in data]
    finding = data.get("finding")
    if "finding" in data and finding not in FINDINGS:
        problems.append(f"finding {finding!r} is not one of {', '.join(FINDINGS)}")
        finding = None
    above = _above_limit(data[ABOVE_LIMIT], problems) if ABOVE_LIMIT in data else None
    reliable = data.get("basis_reliable")
    if "basis_reliable" in data and reliable is not None and not isinstance(reliable, bool):
        problems.append(f"basis_reliable {reliable!r} is not true, false or null")
        reliable = None
    amounts: dict[str, Decimal | None] = {}
    for name in AMOUNTS:
        try:
            amounts[name] = money(data.get(name))
        except NotMoney:
            problems.append(f"{name} {data[name]!r} is not money")
            amounts[name] = None
    if "explanation" in data and not isinstance(data["explanation"], str):
        problems.append("explanation is not text")
    issues = reviewer_issues(data, problems)
    cited = figures(data["figures"], problems) if "figures" in data else ()
    return _Answer(
        finding=str(finding) if finding is not None else None,
        above_limit=above,
        basis_reliable=reliable if isinstance(reliable, bool) else None,
        amounts=amounts,
        issues=issues,
        figures=cited,
        problems=tuple(problems),
    )


def _amount_ok(value: Decimal | None, expected: Decimal) -> bool:
    if expected == 0:
        return value is None or close(value, expected)
    return close(value, expected)


def _shown(value: Decimal | None) -> str:
    return "none" if value is None else fmt(value)


def grade(output_text: str, key: ConcentrationBasisKey, fixtures: Path) -> Grade:
    answer = _answer(output_text)
    expected_above = key.above_limit
    named = answer.above_limit
    concentration_ok = (
        named is not None
        and set(named) == set(expected_above)
        and all(close(named[s], v) for s, v in expected_above.items())
    )
    key_amounts = {"basis_understated": key.basis_understated, "gain_overstated": key.gain_overstated}
    basis_ok = answer.basis_reliable is key.basis_reliable and all(
        _amount_ok(answer.amounts[name], value) for name, value in key_amounts.items()
    )
    shown_above: Any = "unreadable" if named is None else {s: _shown(v) for s, v in sorted(named.items())}
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
        (
            CONCENTRATION,
            POINTS[CONCENTRATION],
            concentration_ok,
            f"answer {shown_above}, key { ({s: fmt(v) for s, v in sorted(expected_above.items())}) }",
        ),
        (
            BASIS,
            POINTS[BASIS],
            basis_ok,
            f"reliable: answer {answer.basis_reliable}, key {key.basis_reliable}; "
            + "; ".join(f"{n}: answer {_shown(answer.amounts[n])}, key {fmt(v)}" for n, v in key_amounts.items()),
        ),
        issues_result(answer.issues, key.issues, POINTS[ISSUES]),
    ]
    support = Support(fixtures, [f.value for f in key.computed_figures])
    headline = [(name, answer.amounts[name]) for name in AMOUNTS]
    headline += [(f"{ABOVE_LIMIT} {s}", v) for s, v in sorted((named or {}).items())]
    critical = support.first_fabrication(output_text, answer.figures, headline)
    counts = counts_for(answer.finding, key.finding, alarm=(ISSUES_FOUND,), clean=(NO_ISSUES,))
    return grade_from(results, critical, counts, essential=(FINDING, CONCENTRATION, BASIS))
