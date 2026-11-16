"""The grader for an RMD review of one household (T-TAX-01 and T-TAX-02): was every 2025 required minimum
distribution taken, from the right accounts, by its deadline.

Scored against `keys.rmd`: the finding (30) and the RMDs missed, each with its shortfall (25), are
essential; each account's RMD (25) and the total shortfall (10) are the working; output parses (10). An
entry in "missed" names the accounts whose RMD was short: one 401(k) or inherited IRA, or some or all of
an owner's traditional IRAs, which are met together.

A factor or distribution period read from the IRS life-expectancy tables is in no file of the household:
it is accepted when cited with the source `TABLE_SOURCE` and it is one the key uses. Every other figure
follows the fabricated-figure rule of `graders.common`.
"""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from casebook.graders.common import (
    OUTPUT_PARSES,
    TABLE_SOURCE,
    UNRESOLVED,
    Figure,
    Grade,
    NotMoney,
    Support,
    close,
    counts_for,
    figures,
    file_figures,
    grade_from,
    json_block,
    money,
)
from casebook.keys.rmd import ALL_RMDS_MET, RMD_MISSED, HouseholdRmd, Requirement
from casebook.model.money import fmt

FINDINGS = (RMD_MISSED, ALL_RMDS_MET, UNRESOLVED)
REQUIRED_FIELDS = ("finding", "rmds", "missed", "total_shortfall", "figures", "explanation")
# Where an answer cites a life-expectancy factor from: the IRS tables, not a file of the household.

FINDING = "finding"
MISSED = "missed"
RMDS = "rmds"
TOTAL = "total_shortfall"
POINTS = {OUTPUT_PARSES: 10, FINDING: 30, MISSED: 25, RMDS: 25, TOTAL: 10}


@dataclass(frozen=True)
class _Entry:
    account_ids: frozenset[str]
    amount: Decimal | None


@dataclass(frozen=True)
class _Answer:
    finding: str | None
    rmds: tuple[_Entry, ...]
    missed: tuple[_Entry, ...]
    total_shortfall: Decimal | None
    figures: tuple[Figure, ...]
    problems: tuple[str, ...]
    # The fields present and readable.
    well_formed: frozenset[str]


def _accounts(item: dict[str, Any]) -> frozenset[str]:
    if isinstance(item.get("account_ids"), list):
        return frozenset(str(a) for a in item["account_ids"])
    if isinstance(item.get("account_id"), str):
        return frozenset({item["account_id"]})
    return frozenset()


def _entries(data: dict[str, Any], name: str, amount: str, problems: list[str]) -> tuple[_Entry, ...]:
    raw = data.get(name)
    if raw is None:
        return ()
    if not isinstance(raw, list):
        problems.append(f"{name} is not a list")
        return ()
    found: list[_Entry] = []
    for index, item in enumerate(raw):
        accounts = _accounts(item) if isinstance(item, dict) else frozenset()
        if not accounts:
            problems.append(f"{name}[{index}] names no account")
            continue
        try:
            value = money(item.get(amount))
        except NotMoney:
            problems.append(f"{name}[{index}] {amount} {item.get(amount)!r} is not money")
            value = None
        found.append(_Entry(accounts, value))
    return tuple(found)


def _answer(output_text: str) -> _Answer:
    data = json_block(output_text)
    if isinstance(data, str):
        return _Answer(None, (), (), None, (), (data,), frozenset())
    problems = [f"lacks {name}" for name in REQUIRED_FIELDS if name not in data]
    well_formed = {name for name in REQUIRED_FIELDS if name in data}
    finding = data.get("finding")
    if "finding" in data and finding not in FINDINGS:
        problems.append(f"finding {finding!r} is not one of {', '.join(FINDINGS)}")
        finding = None
    try:
        total = money(data.get("total_shortfall"))
    except NotMoney:
        problems.append(f"total_shortfall {data['total_shortfall']!r} is not money")
        well_formed.discard("total_shortfall")
        total = None
    if "explanation" in data and not isinstance(data["explanation"], str):
        problems.append("explanation is not text")
    return _Answer(
        finding=str(finding) if finding is not None else None,
        rmds=_entries(data, "rmds", "rmd", problems),
        missed=_entries(data, "missed", "shortfall", problems),
        total_shortfall=total,
        figures=figures(data["figures"], problems) if "figures" in data else (),
        problems=tuple(problems),
        well_formed=frozenset(well_formed),
    )


def _missed_ok(answer: _Answer, key: tuple[Requirement, ...]) -> tuple[bool, str]:
    """Each RMD the key finds short is named once with its shortfall, and nothing else is named."""
    if "missed" not in answer.well_formed:
        return False, "no missed list"
    unmatched = list(answer.missed)
    problems: list[str] = []
    for r in key:
        entry = next((e for e in unmatched if e.account_ids <= set(r.account_ids)), None)
        if entry is None:
            problems.append(f"{' + '.join(r.account_ids)} not named")
            continue
        unmatched.remove(entry)
        if not close(entry.amount, r.shortfall):
            shown = "none" if entry.amount is None else fmt(entry.amount)
            problems.append(f"{' + '.join(r.account_ids)} short {shown}, key {fmt(r.shortfall)}")
    problems += [f"{', '.join(sorted(e.account_ids))} named but not short" for e in unmatched]
    return not problems, "; ".join(problems) or f"{len(key)} named, each with its shortfall"


def _shown(value: Decimal | None) -> str:
    return "none" if value is None else fmt(value)


def _rmds_ok(answer: _Answer, key: HouseholdRmd) -> tuple[bool, str]:
    """Each account that owes a 2025 RMD is listed on its own with it; any other account listed owes nothing."""
    if "rmds" not in answer.well_formed:
        return False, "no rmds list"
    given = {a: e.amount for e in answer.rmds for a in e.account_ids if len(e.account_ids) == 1}
    problems = [
        f"{a.account_id} {_shown(given.get(a.account_id))}, key {fmt(a.rmd)}"
        for a in key.accounts
        if not close(given.get(a.account_id), a.rmd)
    ]
    owing = {a.account_id for a in key.accounts}
    problems += [f"{a} owes none, answer {_shown(v)}" for a, v in given.items() if a not in owing and v]
    return not problems, "; ".join(problems) or "every account's RMD within $1"


def grade(output_text: str, key: HouseholdRmd, fixtures: Path) -> Grade:
    answer = _answer(output_text)
    missed_ok, missed_detail = _missed_ok(answer, key.missed)
    rmds_ok, rmds_detail = _rmds_ok(answer, key)
    if key.missed:
        total_ok = close(answer.total_shortfall, key.total_shortfall)
    else:
        total_ok = "total_shortfall" in answer.well_formed and (
            answer.total_shortfall is None or close(answer.total_shortfall, key.total_shortfall)
        )
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
        (MISSED, POINTS[MISSED], missed_ok, missed_detail),
        (RMDS, POINTS[RMDS], rmds_ok, rmds_detail),
        (TOTAL, POINTS[TOTAL], total_ok, f"answer {_shown(answer.total_shortfall)}, key {fmt(key.total_shortfall)}"),
    ]
    support = Support(fixtures, [f.value for f in key.computed_figures], key.table_figures)
    headline = [("total_shortfall", answer.total_shortfall)]
    headline += [(f"rmd of {', '.join(sorted(e.account_ids))}", e.amount) for e in answer.rmds]
    headline += [(f"shortfall of {', '.join(sorted(e.account_ids))}", e.amount) for e in answer.missed]
    critical = support.first_fabrication(output_text, file_figures(answer.figures, key.table_figures), headline)
    counts = counts_for(answer.finding, key.finding, alarm=(RMD_MISSED,), clean=(ALL_RMDS_MET,))
    return grade_from(results, critical, counts, essential=(FINDING, MISSED))


__all__ = ["TABLE_SOURCE", "file_figures", "grade"]
