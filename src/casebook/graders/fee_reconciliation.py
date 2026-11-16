"""The grader for a fee reconciliation task: scores an answer's closing json block against the fee key.

The fabricated-figure rule and the three counts are `graders.common`'s; the key lists the figures this
task invites an answer to derive.
"""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from casebook.graders.common import (
    CORRECT_UNRESOLVED,
    FALSE_ALARM,
    OUTPUT_PARSES,
    TOLERANCE,
    UNNECESSARY_REFUSAL,
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
from casebook.keys.fee_reconciliation import FeeKey
from casebook.model.money import fmt

FINDINGS = ("fee_error", "no_fee_error", "unresolved")
REQUIRED_FIELDS = ("finding", "debited_fee", "correct_fee", "amount_misbilled", "figures", "explanation")

FINDING = "finding"
AMOUNT = "amount"
FEES = "fees"
POINTS = {OUTPUT_PARSES: 10, FINDING: 40, AMOUNT: 30, FEES: 20}


@dataclass(frozen=True)
class _Answer:
    """What could be read from the json block; None where a field is absent or malformed."""

    finding: str | None
    debited_fee: Decimal | None
    correct_fee: Decimal | None
    amount_misbilled: Decimal | None
    figures: tuple[Figure, ...]
    problems: tuple[str, ...]
    well_formed: frozenset[str]


def _answer(output_text: str) -> _Answer:
    data = json_block(output_text)
    if isinstance(data, str):
        return _Answer(None, None, None, None, (), (data,), frozenset())
    problems = [f"lacks {name}" for name in REQUIRED_FIELDS if name not in data]
    finding = data.get("finding")
    if "finding" in data and finding not in FINDINGS:
        problems.append(f"finding {finding!r} is not one of {', '.join(FINDINGS)}")
        finding = None
    well_formed = {name for name in REQUIRED_FIELDS if name in data}
    amounts: dict[str, Decimal | None] = {}
    for name in ("debited_fee", "correct_fee", "amount_misbilled"):
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
        debited_fee=amounts["debited_fee"],
        correct_fee=amounts["correct_fee"],
        amount_misbilled=amounts["amount_misbilled"],
        figures=cited,
        problems=tuple(problems),
        well_formed=frozenset(well_formed),
    )


def grade(output_text: str, key: FeeKey, fixtures: Path) -> Grade:
    answer = _answer(output_text)

    found = answer.finding
    finding_ok = found == key.finding
    if key.finding == "no_fee_error":
        amount_ok = "amount_misbilled" in answer.well_formed and (
            answer.amount_misbilled is None or close(answer.amount_misbilled, key.amount_misbilled)
        )
        amount_rule = f"0 or null (key {fmt(key.amount_misbilled)})"
    else:
        amount_ok = close(answer.amount_misbilled, key.amount_misbilled)
        amount_rule = f"within {fmt(TOLERANCE)} of {fmt(key.amount_misbilled)}"
    fees_ok = close(answer.debited_fee, key.debited_fee) and close(answer.correct_fee, key.correct_fee)

    def shown(value: Decimal | None) -> str:
        return "none" if value is None else fmt(value)

    results = [
        (
            OUTPUT_PARSES,
            POINTS[OUTPUT_PARSES],
            not answer.problems,
            "; ".join(answer.problems) or "every required field present",
        ),
        (FINDING, POINTS[FINDING], finding_ok, f"answer {found or 'none'}, key {key.finding}"),
        (AMOUNT, POINTS[AMOUNT], amount_ok, f"answer {shown(answer.amount_misbilled)}, needs {amount_rule}"),
        (
            FEES,
            POINTS[FEES],
            fees_ok,
            f"debited {shown(answer.debited_fee)} vs {fmt(key.debited_fee)}, "
            f"correct {shown(answer.correct_fee)} vs {fmt(key.correct_fee)}",
        ),
    ]
    support = Support(fixtures, [f.value for f in key.computed_figures])
    critical = support.first_fabrication(
        output_text,
        answer.figures,
        (
            ("debited_fee", answer.debited_fee),
            ("correct_fee", answer.correct_fee),
            ("amount_misbilled", answer.amount_misbilled),
        ),
    )
    counts = {
        # The fee key always settles the question (it raises otherwise), so "unresolved" is never correct here.
        CORRECT_UNRESOLVED: 0,
        UNNECESSARY_REFUSAL: int(found == "unresolved"),
        FALSE_ALARM: int(found == "fee_error" and key.finding == "no_fee_error"),
    }
    return grade_from(results, critical, counts, essential=(FINDING, AMOUNT))
