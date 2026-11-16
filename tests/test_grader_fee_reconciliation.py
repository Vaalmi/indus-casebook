"""The fee reconciliation grader: a clean control passes, defective outputs fail, a fabricated figure zeroes."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from reportlab.pdfgen.canvas import Canvas

from casebook.graders.fee_reconciliation import grade
from casebook.keys.fee_reconciliation import FeeKey, KeyFigure, KeyFinding, KeyGroup, fee_key
from casebook.model.files import TRANSACTIONS_COLUMNS, csv_text

A = "SYN-00010001"
B = "SYN-00010002"
STATEMENT = "documents/statement-SYN-00010001-2026Q1.pdf"


def _key(finding: KeyFinding, correct: str, misbilled: str) -> FeeKey:
    return FeeKey(
        household_id="HH-0001",
        quarter_end=date(2026, 3, 31),
        fee_date=date(2026, 4, 2),
        finding=finding,
        debited_fee=Decimal("2750.00"),
        correct_fee=Decimal(correct),
        amount_misbilled=Decimal(misbilled),
        billing_groups=(
            KeyGroup((A, B), "FS-STD", ("BG-0001-1", "BG-0001-2"), Decimal("1100000.00"), Decimal(correct)),
        ),
        computed_figures=(
            KeyFigure("combined value", Decimal("1100000.00")),
            KeyFigure("fees debited", Decimal("2750.00")),
            KeyFigure("correct fee", Decimal(correct)),
            KeyFigure("amount misbilled", Decimal(misbilled)),
        ),
    )


FEE_ERROR_KEY = _key("fee_error", "2700.00", "50.00")
NO_FEE_ERROR_KEY = _key("no_fee_error", "2750.00", "0.00")


def _fee_row(transaction_id: str, account: str, amount: str) -> dict[str, str]:
    row: dict[str, str] = dict.fromkeys(TRANSACTIONS_COLUMNS, "")
    day = "2026-04-02"
    row.update(
        transaction_id=transaction_id,
        account_id=account,
        trade_date=day,
        settle_date=day,
        type="FEE",
        amount=amount,
        description="Advisory fee, quarter to 2026-03-31",
        valuation_date=day,
        known_as_of=day,
    )
    return row


@pytest.fixture
def fixtures(tmp_path: Path) -> Path:
    transactions = tmp_path / "custodian" / "transactions.csv"
    transactions.parent.mkdir(parents=True)
    rows = [_fee_row("T-2", A, "-1500.00"), _fee_row("T-3", B, "-1250.00")]
    transactions.write_text(csv_text(TRANSACTIONS_COLUMNS, rows), encoding="utf-8")
    statement = tmp_path / STATEMENT
    statement.parent.mkdir(parents=True)
    canvas = Canvas(str(statement))
    canvas.drawString(72, 720, "Holdings on 2026-03-31  Total $600,000.00")
    canvas.save()
    (tmp_path / "crm").mkdir()
    (tmp_path / "crm" / "crm.json").write_text('{"agreements": []}\n', encoding="utf-8")
    return tmp_path


def _output(**fields: Any) -> str:
    answer: dict[str, Any] = {
        "finding": "fee_error",
        "debited_fee": "$2,750.00",
        "correct_fee": 2700.0,
        "amount_misbilled": "50.00",
        "figures": [
            {"label": "Fee debited on the joint account", "value": "-1,500.00", "source": "custodian/transactions.csv"},
            {"label": "Joint account value", "value": 600000, "source": STATEMENT},
            {"label": "Fee under the agreement", "value": "2,700.60", "source": "crm/crm.json", "computed": True},
        ],
        "explanation": "The householding agreement puts both accounts in one group.",
    }
    answer.update(fields)
    return f"The fees were overbilled.\n\n```json\n{json.dumps(answer, indent=2)}\n```\n"


def _earned(output: str, key: FeeKey, fixtures: Path) -> dict[str, int]:
    return {c.name: c.earned for c in grade(output, key, fixtures).breakdown}


NO_COUNTS = {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 0}


def test_a_clean_control_passes(fixtures: Path) -> None:
    result = grade(_output(), FEE_ERROR_KEY, fixtures)
    assert result.score == 100
    assert result.passed
    assert result.critical_fail is None
    assert result.counts == NO_COUNTS


def test_a_clean_control_on_the_twin_passes(fixtures: Path) -> None:
    output = _output(finding="no_fee_error", correct_fee="2,750.00", amount_misbilled=None, figures=[])
    result = grade(output, NO_FEE_ERROR_KEY, fixtures)
    assert result.score == 100
    assert result.passed


def test_a_wrong_finding_fails(fixtures: Path) -> None:
    output = _output(finding="no_fee_error", correct_fee="2750.00", amount_misbilled=0, figures=[])
    result = grade(output, FEE_ERROR_KEY, fixtures)
    assert _earned(output, FEE_ERROR_KEY, fixtures) == {"output_parses": 10, "finding": 0, "amount": 0, "fees": 0}
    assert result.score == 10
    assert not result.passed


def test_the_right_finding_with_a_wrong_amount_fails(fixtures: Path) -> None:
    # 2,250.00 and 500.00 are in no file and follow from none: fabricated, so zero, breakdown kept.
    output = _output(correct_fee="2250.00", amount_misbilled="500.00", figures=[])
    result = grade(output, FEE_ERROR_KEY, fixtures)
    assert _earned(output, FEE_ERROR_KEY, fixtures) == {"output_parses": 10, "finding": 40, "amount": 0, "fees": 0}
    assert result.score == 0
    assert result.critical_fail == "fabricated figure: correct_fee = 2250.00 is in no file and follows from none"
    assert not result.passed


@pytest.mark.parametrize(
    ("fields", "prose", "fabricated"),
    [
        # Reviewers A and B, slice 2 round 1, S1: invented fee fields scored 80 and passed.
        ({"debited_fee": "999999999.00", "correct_fee": "999999949.00"}, "", "debited_fee = 999999999.00"),
        # ... and an invented amount in the prose scored 100.
        ({}, "The joint account also held $48,113.27 in cash.", "'$48,113.27' in the answer"),
    ],
)
def test_a_figure_outside_the_figures_list_is_checked_too(
    fixtures: Path, fields: dict[str, str], prose: str, fabricated: str
) -> None:
    result = grade(prose + "\n" + _output(figures=[], **fields), FEE_ERROR_KEY, fixtures)
    assert result.score == 0
    assert result.critical_fail is not None and fabricated in result.critical_fail


def test_right_fees_with_a_wrong_amount_still_fail(fixtures: Path) -> None:
    # Scores 70 (parses, finding, fees) but the amount is the point of the task, so it does not pass.
    output = _output(amount_misbilled="-50.00", figures=[])
    result = grade(output, FEE_ERROR_KEY, fixtures)
    assert result.score == 70
    assert not result.passed


def test_an_unnecessary_refusal_fails_and_is_counted(fixtures: Path) -> None:
    output = _output(finding="unresolved", correct_fee=None, amount_misbilled=None, figures=[])
    result = grade(output, FEE_ERROR_KEY, fixtures)
    assert result.score == 10
    assert not result.passed
    assert result.counts == {"correct_unresolved": 0, "unnecessary_refusal": 1, "false_alarm": 0}


def test_a_false_alarm_on_the_twin_is_counted(fixtures: Path) -> None:
    result = grade(_output(figures=[]), NO_FEE_ERROR_KEY, fixtures)
    assert not result.passed
    assert result.counts == {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 1}


@pytest.mark.parametrize(
    "figure",
    [
        {"label": "Householding discount", "value": "$1,234.56", "source": "custodian/transactions.csv"},
        {
            "label": "Householding discount",
            "value": "1234.56",
            "source": "custodian/transactions.csv",
            "computed": True,
        },
        {"label": "Householding discount", "value": "1234.56", "source": "custodian/fee_report.csv"},
        {"label": "Householding discount", "value": "1234.56", "source": "../outside.csv"},
    ],
    ids=["not in the source", "computed but not by the key", "source missing", "source outside the fixtures"],
)
def test_a_fabricated_figure_scores_zero_and_keeps_its_breakdown(fixtures: Path, figure: dict[str, Any]) -> None:
    (fixtures.parent / "outside.csv").write_text("1234.56\n", encoding="utf-8")
    output = _output(figures=[figure])
    result = grade(output, FEE_ERROR_KEY, fixtures)
    assert result.score == 0
    assert not result.passed
    assert result.critical_fail is not None
    assert "Householding discount" in result.critical_fail
    assert "1234.56" in result.critical_fail
    assert _earned(output, FEE_ERROR_KEY, fixtures) == {"output_parses": 10, "finding": 40, "amount": 30, "fees": 20}


def test_an_answer_with_no_json_block_fails_output_parses(fixtures: Path) -> None:
    output = "The fees were overbilled by $50.00."
    result = grade(output, FEE_ERROR_KEY, fixtures)
    assert _earned(output, FEE_ERROR_KEY, fixtures) == {"output_parses": 0, "finding": 0, "amount": 0, "fees": 0}
    assert result.score == 0
    assert not result.passed


def test_a_block_missing_a_field_loses_only_output_parses(fixtures: Path) -> None:
    output = _output(figures=[]).replace('"explanation"', '"notes"')
    result = grade(output, FEE_ERROR_KEY, fixtures)
    assert _earned(output, FEE_ERROR_KEY, fixtures) == {"output_parses": 0, "finding": 40, "amount": 30, "fees": 20}
    assert result.score == 90


def test_the_grade_writes_as_json(fixtures: Path) -> None:
    data = grade("no block", FEE_ERROR_KEY, fixtures).to_dict()
    assert data["score"] == 0
    assert data["passed"] is False
    assert data["counts"] == NO_COUNTS
    assert [c["name"] for c in data["breakdown"]] == ["output_parses", "finding", "amount", "fees"]
    assert [c["points"] for c in data["breakdown"]] == [10, 40, 30, 20]
    json.dumps(data)


LIVE = Path(__file__).parent / "fixtures" / "live"


@pytest.mark.parametrize(
    "answer",
    ["basic", "checklist", "skill", "basic-second", "checklist-second", "skill-second", "checklist-third"],
)
def test_the_live_answers_are_graded_as_the_correct_answers_they_are(answer: str) -> None:
    # Slice 2's live runs (16 November 2026), mapped to aliases. All six found the $508.56
    # overbilling with sourced figures. The grader first zeroed one for a positions total it called
    # fabricated and docked all three for citing dates; a later rule zeroed "skill-second" for an
    # account's value on 31 December 2025, and "checklist-third" for the correct fee shared across
    # the accounts by value. Each follows from the files; the key now lists them.
    # They answered the book's first price draw, before the version left the seed (decision of
    # 16 November 2026), so they are graded against a copy of the files they read.
    household = LIVE / "HH-4821-first-draw"
    key = fee_key(household, date(2026, 3, 31))
    result = grade((LIVE / f"T-REC-01-{answer}.md").read_text(), key, household)
    assert (result.score, result.critical_fail) == (100, None)


@pytest.mark.parametrize("arm", ["basic", "checklist", "skill"])
def test_the_published_live_answers_are_correct_against_the_current_book(book: Path, arm: str) -> None:
    # The three published runs (16 November 2026, Opus 5.5 at high effort), against the book as it
    # is drawn now. A change to the book that moves their figures makes them stale, and fails here.
    household = book / "households" / "HH-4821"
    key = fee_key(household, date(2026, 3, 31))
    result = grade((LIVE / f"T-REC-01-{arm}-second-draw.md").read_text(), key, household)
    assert (result.score, result.critical_fail) == (100, None)


@pytest.mark.parametrize(
    "prose",
    [
        "The joint account also held USD 48,113.27 in cash.",
        "The joint account also held 48,113.27 dollars in cash.",
        "The household is worth $50 million.",
        "The fee was 4944.13 for the quarter.",
    ],
)
def test_an_invented_amount_in_any_money_form_is_fabricated(fixtures: Path, prose: str) -> None:
    # Reviewers A and B, slice 2 round 2, S1 held: amounts without a dollar sign, or with a multiplier, passed.
    result = grade(prose + "\n" + _output(figures=[]), FEE_ERROR_KEY, fixtures)
    assert result.score == 0 and result.critical_fail is not None


def test_a_date_that_is_not_in_its_source_is_fabricated(fixtures: Path) -> None:
    figure = {"label": "Householding letter signed", "value": "2023-01-05", "source": "crm/crm.json"}
    result = grade(_output(figures=[figure]), FEE_ERROR_KEY, fixtures)
    assert result.critical_fail == "fabricated figure: Householding letter signed = 2023-01-05 (cited crm/crm.json)"


def test_a_text_figure_listing_several_supported_amounts_is_not_fabricated(fixtures: Path) -> None:
    # Slice 2's third live checklist run cited "51340.38 / 6815.97 / 10713.51" from cash.csv as one figure.
    figure = {"label": "Fees debited", "value": "1500.00 / 1250.00", "source": "custodian/transactions.csv"}
    assert grade(_output(figures=[figure]), FEE_ERROR_KEY, fixtures).critical_fail is None
    invented = {"label": "Fees debited", "value": "1500.00 / 1234.56", "source": "custodian/transactions.csv"}
    assert grade(_output(figures=[invented]), FEE_ERROR_KEY, fixtures).critical_fail is not None
