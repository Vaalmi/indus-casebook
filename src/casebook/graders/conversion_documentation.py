"""The grader for whether a Roth conversion is documented well enough to report its taxable amount (T-CMP-03
and T-CMP-04): scores an answer's closing json block against `keys.conversion_documentation`.

- finding (30, essential): "documented" or "unresolved", as the key finds;
- taxable amount (30, essential): where the key settles it, the taxable amount and the basis on file each
  within a dollar; where it does not, no taxable amount (null), since basis can be neither assumed nor ruled out;
- converted (10): the amount converted, within a dollar;
- issues named (20): each issue the key expects, named in one entry of "issues_for_reviewer" by its records;
- output parses (10).

The fabricated-figure rule and the three counts are `graders.common`'s. Neither finding is an alarm, so no
answer here is a false alarm; "unresolved" is correct only where the key leaves it so.
"""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

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
from casebook.graders.compliance_review import ISSUES_FOR_REVIEWER, ReviewerIssues, issues_result, reviewer_issues
from casebook.keys.conversion_documentation import DOCUMENTED, UNRESOLVED, ConversionKey
from casebook.model.money import fmt

FINDINGS = (DOCUMENTED, UNRESOLVED)
AMOUNTS = ("converted", "basis_on_file", "taxable_amount")
REQUIRED_FIELDS = ("finding", *AMOUNTS, ISSUES_FOR_REVIEWER, "figures", "explanation")

FINDING = "finding"
TAXABLE = "taxable_amount"
CONVERTED = "converted"
ISSUES = "issues_named"
POINTS = {OUTPUT_PARSES: 10, FINDING: 30, TAXABLE: 30, CONVERTED: 10, ISSUES: 20}


@dataclass(frozen=True)
class _Answer:
    finding: str | None
    amounts: dict[str, Decimal | None]
    # The fields present and readable: a taxable amount of null is an answer only where it was given.
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
        issues_result(answer.issues, key.issues, POINTS[ISSUES]),
    ]
    support = Support(fixtures, [f.value for f in key.computed_figures])
    critical = support.first_fabrication(output_text, answer.figures, [(n, answer.amounts[n]) for n in AMOUNTS])
    counts = counts_for(answer.finding, key.finding, alarm=(), clean=())
    return grade_from(results, critical, counts, essential=(FINDING, TAXABLE))
