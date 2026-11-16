"""The grader for a wash-sale review: scores an answer's closing json block against the wash-sale key.

Losses are compared as amounts, whatever their sign: an answer may write a loss of $500 as 500 or -500.
Every amount is essential: the finding, the disallowed loss it turns on, and the loss reported and allowed,
which are the answer to "deductible as reported?".
The fabricated-figure rule and the three counts are `graders.common`'s; the key lists the figures this
task invites an answer to derive.
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
from casebook.keys.wash_sales import WashSaleKey
from casebook.model.money import fmt

WASH_SALE, NO_WASH_SALE = "wash_sale", "no_wash_sale"
FINDINGS = (WASH_SALE, NO_WASH_SALE, UNRESOLVED)
AMOUNT_FIELDS = ("loss_reported", "disallowed_loss", "allowed_loss")
REQUIRED_FIELDS = ("finding", *AMOUNT_FIELDS, "figures", "explanation")

FINDING = "finding"
DISALLOWED = "disallowed"
LOSSES = "losses"
POINTS = {OUTPUT_PARSES: 10, FINDING: 40, DISALLOWED: 30, LOSSES: 20}


@dataclass(frozen=True)
class _Answer:
    """What could be read from the json block; None where a field is absent or malformed."""

    finding: str | None
    amounts: dict[str, Decimal | None]
    figures: tuple[Figure, ...]
    problems: tuple[str, ...]
    well_formed: frozenset[str]


def _answer(output_text: str) -> _Answer:
    data = json_block(output_text)
    if isinstance(data, str):
        return _Answer(None, dict.fromkeys(AMOUNT_FIELDS), (), (data,), frozenset())
    problems = [f"lacks {name}" for name in REQUIRED_FIELDS if name not in data]
    finding = data.get("finding")
    if "finding" in data and finding not in FINDINGS:
        problems.append(f"finding {finding!r} is not one of {', '.join(FINDINGS)}")
        finding = None
    well_formed = {name for name in REQUIRED_FIELDS if name in data}
    amounts: dict[str, Decimal | None] = {}
    for name in AMOUNT_FIELDS:
        try:
            amounts[name] = money(data.get(name))
        except NotMoney:
            problems.append(f"{name} {data[name]!r} is not money")
            well_formed.discard(name)
            amounts[name] = None
    if "explanation" in data and not isinstance(data["explanation"], str):
        problems.append("explanation is not text")
    cited = figures(data["figures"], problems) if "figures" in data else ()
    return _Answer(
        finding=str(finding) if finding is not None else None,
        amounts=amounts,
        figures=cited,
        problems=tuple(problems),
        well_formed=frozenset(well_formed),
    )


def _size(value: Decimal | None) -> Decimal | None:
    return None if value is None else abs(value)


def grade(output_text: str, key: WashSaleKey, fixtures: Path) -> Grade:
    answer = _answer(output_text)
    found = answer.finding
    loss, disallowed, allowed = (_size(answer.amounts[name]) for name in AMOUNT_FIELDS)

    if key.finding == NO_WASH_SALE:
        disallowed_ok = "disallowed_loss" in answer.well_formed and (disallowed is None or disallowed == 0)
        disallowed_rule = "0 or null"
    else:
        disallowed_ok = close(disallowed, key.disallowed_loss)
        disallowed_rule = f"within {fmt(TOLERANCE)} of {fmt(key.disallowed_loss)}"
    losses_ok = close(loss, key.loss_reported) and close(allowed, key.allowed_loss)

    def shown(value: Decimal | None) -> str:
        return "none" if value is None else fmt(value)

    results = [
        (
            OUTPUT_PARSES,
            POINTS[OUTPUT_PARSES],
            not answer.problems,
            "; ".join(answer.problems) or "every required field present",
        ),
        (FINDING, POINTS[FINDING], found == key.finding, f"answer {found or 'none'}, key {key.finding}"),
        (DISALLOWED, POINTS[DISALLOWED], disallowed_ok, f"answer {shown(disallowed)}, needs {disallowed_rule}"),
        (
            LOSSES,
            POINTS[LOSSES],
            losses_ok,
            f"reported {shown(loss)} vs {fmt(key.loss_reported)}, allowed {shown(allowed)} vs {fmt(key.allowed_loss)}",
        ),
    ]
    support = Support(fixtures, [f.value for f in key.computed_figures])
    critical = support.first_fabrication(
        output_text, answer.figures, tuple((name, answer.amounts[name]) for name in AMOUNT_FIELDS)
    )
    counts = counts_for(found, key.finding, alarm=(WASH_SALE,), clean=(NO_WASH_SALE,))
    return grade_from(results, critical, counts, essential=(FINDING, DISALLOWED, LOSSES))
