"""The grader for what part of a household's 2025 traditional IRA distributions is taxable, counting any
qualified charitable distribution: scores an answer's closing json block against `keys.ira_distributions`.

A QCD is excluded from income (26 U.S.C. § 408(d)(8)), so the taxable part is what left the IRAs less the QCDs
the CRM evidences, whether or not the custodian recorded them as QCDs. The finding says whether the custodian's
transactions record a QCD as an ordinary distribution, and so show more as ordinary distributions than is taxable.

- finding (25, essential): "records_disagree" or "records_agree", as the key finds;
- taxable distributions (30, essential): within a dollar of the key's;
- QCD amount (20, essential): the QCDs excluded, within a dollar;
- custodian distributions (15): what left the IRAs, distributions and QCDs together, within a dollar;
- output parses (10).

A life-expectancy factor cited from `TABLE_SOURCE` is judged as `graders.rmd_review` judges it; every other
figure follows the fabricated-figure rule of `graders.common`, as do the three counts. The key always settles the
question, so "unresolved" is an unnecessary refusal; "records_disagree" where the key finds the records agree is
a false alarm.
"""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

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
    file_figures,
    grade_from,
    json_block,
    money,
)
from casebook.keys.ira_distributions import RECORDS_AGREE, RECORDS_DISAGREE, IraDistributionsKey
from casebook.model.money import fmt

FINDINGS = (RECORDS_DISAGREE, RECORDS_AGREE, UNRESOLVED)
AMOUNTS = ("custodian_distributions", "qcd_amount", "taxable_distributions")
REQUIRED_FIELDS = ("finding", *AMOUNTS, "figures", "explanation")

FINDING = "finding"
TAXABLE = "taxable_distributions"
QCD_AMOUNT = "qcd_amount"
DISTRIBUTED = "custodian_distributions"
POINTS = {OUTPUT_PARSES: 10, FINDING: 25, TAXABLE: 30, QCD_AMOUNT: 20, DISTRIBUTED: 15}


@dataclass(frozen=True)
class _Answer:
    finding: str | None
    amounts: dict[str, Decimal | None]
    figures: tuple[Figure, ...]
    problems: tuple[str, ...]


def _answer(output_text: str) -> _Answer:
    data = json_block(output_text)
    if isinstance(data, str):
        return _Answer(None, dict.fromkeys(AMOUNTS), (), (data,))
    problems = [f"lacks {name}" for name in REQUIRED_FIELDS if name not in data]
    finding = data.get("finding")
    if "finding" in data and finding not in FINDINGS:
        problems.append(f"finding {finding!r} is not one of {', '.join(FINDINGS)}")
        finding = None
    amounts: dict[str, Decimal | None] = {}
    for name in AMOUNTS:
        try:
            amounts[name] = money(data.get(name))
        except NotMoney:
            problems.append(f"{name} {data[name]!r} is not money")
            amounts[name] = None
    if "explanation" in data and not isinstance(data["explanation"], str):
        problems.append("explanation is not text")
    return _Answer(
        finding=str(finding) if finding is not None else None,
        amounts=amounts,
        figures=figures(data["figures"], problems) if "figures" in data else (),
        problems=tuple(problems),
    )


def _shown(value: Decimal | None) -> str:
    return "none" if value is None else fmt(value)


def _amount(name: str, answer: _Answer, expected: Decimal) -> tuple[str, int, bool, str]:
    given = answer.amounts[name]
    return (name, POINTS[name], close(given, expected), f"answer {_shown(given)}, key {fmt(expected)}")


def grade(output_text: str, key: IraDistributionsKey, fixtures: Path) -> Grade:
    answer = _answer(output_text)
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
        _amount(TAXABLE, answer, key.taxable_distributions),
        _amount(QCD_AMOUNT, answer, key.qcd_amount),
        _amount(DISTRIBUTED, answer, key.custodian_distributions),
    ]
    support = Support(fixtures, [f.value for f in key.computed_figures], key.table_figures)
    critical = support.first_fabrication(
        output_text, file_figures(answer.figures, key.table_figures), [(n, answer.amounts[n]) for n in AMOUNTS]
    )
    counts = counts_for(answer.finding, key.finding, alarm=(RECORDS_DISAGREE,), clean=(RECORDS_AGREE,))
    return grade_from(results, critical, counts, essential=(FINDING, TAXABLE, QCD_AMOUNT))
