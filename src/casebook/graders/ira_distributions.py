"""The grader for T-REC-03 and T-REC-04: do the custodian's 2025 IRA distributions agree with what the CRM
records, and was the RMD met.

Scored against `keys.ira_distributions`: the finding (35), the QCD the CRM evidences (15) and whether the
RMD was met (15) are essential; the RMD (15) and what left the IRA, in all and taxable (10), are the
working; output parses (10). A life-expectancy factor cited from `TABLE_SOURCE` is judged as
`graders.rmd_review` judges it.
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
AMOUNTS = ("qcd_amount", "custodian_distributions", "taxable_distributions", "rmd")
REQUIRED_FIELDS = ("finding", *AMOUNTS, "rmd_met", "figures", "explanation")

FINDING = "finding"
QCD_AMOUNT = "qcd_amount"
RMD_MET = "rmd_met"
RMD = "rmd"
DISTRIBUTIONS = "distributions"
POINTS = {OUTPUT_PARSES: 10, FINDING: 35, QCD_AMOUNT: 15, RMD_MET: 15, RMD: 15, DISTRIBUTIONS: 10}


@dataclass(frozen=True)
class _Answer:
    finding: str | None
    amounts: dict[str, Decimal | None]
    rmd_met: bool | None
    figures: tuple[Figure, ...]
    problems: tuple[str, ...]


def _answer(output_text: str) -> _Answer:
    data = json_block(output_text)
    if isinstance(data, str):
        return _Answer(None, dict.fromkeys(AMOUNTS), None, (), (data,))
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
    met = data.get("rmd_met")
    if met is not None and not isinstance(met, bool):
        problems.append(f"rmd_met {met!r} is not true, false or null")
        met = None
    if "explanation" in data and not isinstance(data["explanation"], str):
        problems.append("explanation is not text")
    return _Answer(
        finding=str(finding) if finding is not None else None,
        amounts=amounts,
        rmd_met=met,
        figures=figures(data["figures"], problems) if "figures" in data else (),
        problems=tuple(problems),
    )


def _shown(value: Decimal | None) -> str:
    return "none" if value is None else fmt(value)


def grade(output_text: str, key: IraDistributionsKey, fixtures: Path) -> Grade:
    answer = _answer(output_text)
    a = answer.amounts
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
            QCD_AMOUNT,
            POINTS[QCD_AMOUNT],
            close(a["qcd_amount"], key.qcd_amount),
            f"answer {_shown(a['qcd_amount'])}, key {fmt(key.qcd_amount)}",
        ),
        (RMD_MET, POINTS[RMD_MET], answer.rmd_met is key.rmd_met, f"answer {answer.rmd_met}, key {key.rmd_met}"),
        (RMD, POINTS[RMD], close(a["rmd"], key.rmd), f"answer {_shown(a['rmd'])}, key {fmt(key.rmd)}"),
        (
            DISTRIBUTIONS,
            POINTS[DISTRIBUTIONS],
            close(a["custodian_distributions"], key.custodian_distributions)
            and close(a["taxable_distributions"], key.taxable_distributions),
            f"distributed {_shown(a['custodian_distributions'])} vs {fmt(key.custodian_distributions)}, "
            f"taxable {_shown(a['taxable_distributions'])} vs {fmt(key.taxable_distributions)}",
        ),
    ]
    support = Support(fixtures, [f.value for f in key.computed_figures], key.table_figures)
    critical = support.first_fabrication(
        output_text, file_figures(answer.figures, key.table_figures), [(name, a[name]) for name in AMOUNTS]
    )
    counts = counts_for(answer.finding, key.finding, alarm=(RECORDS_DISAGREE,), clean=(RECORDS_AGREE,))
    return grade_from(results, critical, counts, essential=(FINDING, QCD_AMOUNT, RMD_MET))
