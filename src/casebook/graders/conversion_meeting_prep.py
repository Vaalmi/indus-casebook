"""The grader for preparing a meeting to review a year's Roth conversion: what part of it is taxable, and what
to bring. Scored against `keys.conversion_documentation`, since the question turns on the same records as the
compliance review of the conversion's documentation.

- finding (30, essential): "documented" or "unresolved", as the key finds;
- taxable amount (30, essential): where the key settles it, the taxable amount and the basis on file each
  within a dollar; where it does not, no taxable amount (null), since basis can be neither assumed nor ruled out;
- converted (10): the amount converted, within a dollar;
- what to bring (20, essential, as half the question): every record the key's issues rest on is named in some
  entry of "to_bring": the Form 1099-R and the Form 8606 on file where the 1099-R's taxable amount is not the
  Form 8606's, or the CRM's records of the prior return and of the client's basis claim where no Form 8606 is
  on file;
- output parses (10).

The fabricated-figure rule and the three counts are `graders.common`'s. Neither finding is an alarm, so no
answer here is a false alarm; "unresolved" is correct only where the key leaves it so.
"""

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from casebook.graders.common import (
    OUTPUT_PARSES,
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
from casebook.keys.conversion_documentation import DOCUMENTED, UNRESOLVED, ConversionKey
from casebook.model.money import fmt

FINDINGS = (DOCUMENTED, UNRESOLVED)
AMOUNTS = ("converted", "basis_on_file", "taxable_amount")
TO_BRING = "to_bring"
BRING_FIELDS = ("item", "records", "why")
REQUIRED_FIELDS = ("finding", *AMOUNTS, TO_BRING, "figures", "explanation")

FINDING = "finding"
TAXABLE = "taxable_amount"
CONVERTED = "converted"
BRING = "to_bring_named"
POINTS = {OUTPUT_PARSES: 10, FINDING: 30, TAXABLE: 30, CONVERTED: 10, BRING: 20}


@dataclass(frozen=True)
class _Answer:
    finding: str | None
    amounts: dict[str, Decimal | None]
    # The amounts present and readable: a taxable amount of null is an answer only where it was given.
    readable: frozenset[str]
    # Each entry of "to_bring" as text, or None where the field is unreadable.
    to_bring: tuple[str, ...] | None
    figures: tuple[Figure, ...]
    problems: tuple[str, ...]


def _to_bring(data: dict[str, Any], problems: list[str]) -> tuple[str, ...] | None:
    if TO_BRING not in data:
        return None
    raw = data[TO_BRING]
    if not isinstance(raw, list):
        problems.append(f"{TO_BRING} is not a list")
        return None
    entries: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or any(f not in item for f in BRING_FIELDS):
            problems.append(f"{TO_BRING}[{index}] lacks one of {', '.join(BRING_FIELDS)}")
            continue
        if not isinstance(item["records"], list):
            problems.append(f"{TO_BRING}[{index}] records is not a list")
            continue
        entries.append(json.dumps(item, default=str))
    return tuple(entries)


def _answer(output_text: str) -> _Answer:
    data = json_block(output_text)
    if isinstance(data, str):
        return _Answer(None, dict.fromkeys(AMOUNTS), frozenset(), None, (), (data,))
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
    to_bring = _to_bring(data, problems)
    cited = figures(data["figures"], problems) if "figures" in data else ()
    return _Answer(
        finding=str(finding) if finding is not None else None,
        amounts=amounts,
        readable=frozenset(readable),
        to_bring=to_bring,
        figures=cited,
        problems=tuple(problems),
    )


def _bring_result(answer: _Answer, key: ConversionKey) -> tuple[str, int, bool, str]:
    if answer.to_bring is None:
        return (BRING, POINTS[BRING], False, f"no readable {TO_BRING}")
    needed = list(dict.fromkeys(r for issue in key.issues for r in issue.records))
    missing = [r for r in needed if not any(r in entry for entry in answer.to_bring)]
    if missing:
        return (BRING, POINTS[BRING], False, f"no entry names {', '.join(missing)}")
    return (BRING, POINTS[BRING], True, f"every record the key needs is named ({len(needed)})")


def _shown(value: Decimal | None) -> str:
    return "null" if value is None else fmt(value)


def grade(output_text: str, key: ConversionKey, fixtures: Path) -> Grade:
    answer = _answer(output_text)
    taxable, basis = answer.amounts["taxable_amount"], answer.amounts["basis_on_file"]
    if key.taxable is None:
        taxable_ok = "taxable_amount" in answer.readable and taxable is None
        rule = "null: the records leave it unresolved"
    else:
        on_file = key.basis_prior or Decimal(0)
        taxable_ok = close(taxable, key.taxable) and close(basis, on_file)
        rule = f"{fmt(key.taxable)} on basis {fmt(on_file)}"
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
        (TAXABLE, POINTS[TAXABLE], taxable_ok, f"answer {_shown(taxable)} on basis {_shown(basis)}, key {rule}"),
        (
            CONVERTED,
            POINTS[CONVERTED],
            close(answer.amounts["converted"], key.converted),
            f"answer {_shown(answer.amounts['converted'])}, key {fmt(key.converted)}",
        ),
        _bring_result(answer, key),
    ]
    support = Support(fixtures, [f.value for f in key.computed_figures])
    critical = support.first_fabrication(output_text, answer.figures, [(n, answer.amounts[n]) for n in AMOUNTS])
    counts = counts_for(answer.finding, key.finding, alarm=(), clean=())
    return grade_from(results, critical, counts, essential=(FINDING, TAXABLE, BRING))
