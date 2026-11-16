"""The wash-sale review grader: clean controls pass, defective outputs fail, a fabricated figure zeroes,
an altered key fails a clean answer, and each result records the three counts."""

import dataclasses
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.wash_sale_review import grade
from casebook.keys.figures import KeyFigure
from casebook.keys.wash_sales import LossLot, Replacement, WashSaleKey, wash_sale_key
from casebook.model.files import REALIZED_COLUMNS, TRANSACTIONS_COLUMNS, csv_text, household_dir

JOINT, IRA = "SYN-00010001", "SYN-00010002"
REALIZED = "custodian/realized_lots.csv"
TRANSACTIONS = "custodian/transactions.csv"


def _lot(units_replaced: str, disallowed: str) -> LossLot:
    replaced = (
        (Replacement("T-2", IRA, "traditional_ira", date(2025, 11, 19), 16, Decimal(units_replaced)),)
        if units_replaced != "0"
        else ()
    )
    return LossLot(
        transaction_id="T-1",
        account_id=JOINT,
        lot_id="L-1",
        security_id="SEC-0025",
        acquired_date=date(2023, 7, 17),
        sold_date=date(2025, 11, 3),
        units=Decimal("100"),
        cost_basis=Decimal("10000.00"),
        proceeds=Decimal("8000.00"),
        replacements=replaced,
        disallowed=Decimal(disallowed),
    )


def _key(units_replaced: str, disallowed: str) -> WashSaleKey:
    # A 2,000.00 loss on 100 units; the replaced units' share of it is disallowed.
    allowed = Decimal("2000.00") - Decimal(disallowed)
    return WashSaleKey(
        household_id="HH-0001",
        finding="wash_sale" if Decimal(disallowed) else "no_wash_sale",
        loss_reported=Decimal("2000.00"),
        disallowed_loss=Decimal(disallowed),
        allowed_loss=allowed,
        loss_lots=(_lot(units_replaced, disallowed),),
        computed_figures=(
            KeyFigure("T-1 lot L-1 loss", Decimal("2000.00")),
            KeyFigure("T-1 lot L-1 loss per unit", Decimal("20.0000")),
            KeyFigure("days from T-1 to T-2", Decimal(16)),
            KeyFigure("disallowed loss", Decimal(disallowed)),
            KeyFigure("allowed loss", allowed),
        ),
    )


# The trap: 60 of the 100 units replaced, 2,000.00 x 60 / 100 = 1,200.00 disallowed. The twin: none.
TRAP = _key("60", "1200.00")
TWIN = _key("0", "0.00")


@pytest.fixture
def fixtures(tmp_path: Path) -> Path:
    realized: dict[str, str] = dict.fromkeys(REALIZED_COLUMNS, "")
    realized.update(
        transaction_id="T-1",
        account_id=JOINT,
        lot_id="L-1",
        security_id="SEC-0025",
        sold_date="2025-11-03",
        units="100",
        cost_basis="10000.00",
        proceeds="8000.00",
        gain="-2000.00",
    )
    buy: dict[str, str] = dict.fromkeys(TRANSACTIONS_COLUMNS, "")
    buy.update(
        transaction_id="T-2",
        account_id=IRA,
        trade_date="2025-11-19",
        type="BUY",
        security_id="SEC-0025",
        units="60",
        price="81.25",
        amount="-4875.00",
    )
    (tmp_path / "custodian").mkdir()
    (tmp_path / REALIZED).write_text(csv_text(REALIZED_COLUMNS, [realized]), encoding="utf-8")
    (tmp_path / TRANSACTIONS).write_text(csv_text(TRANSACTIONS_COLUMNS, [buy]), encoding="utf-8")
    return tmp_path


def _output(**fields: Any) -> str:
    answer: dict[str, Any] = {
        "finding": "wash_sale",
        "loss_reported": "$2,000.00",
        "disallowed_loss": 1200.0,
        "allowed_loss": "-800.00",
        "figures": [
            {"label": "Basis of the units sold", "value": "10,000.00", "source": REALIZED},
            {"label": "Proceeds", "value": 8000, "source": REALIZED},
            {"label": "Sold", "value": "2025-11-03", "source": REALIZED},
            {"label": "Units bought back in the IRA", "value": "60", "source": TRANSACTIONS},
            {"label": "Days from sale to purchase", "value": 16, "source": TRANSACTIONS, "computed": True},
            {"label": "Disallowed loss", "value": "1,200.00", "source": REALIZED, "computed": True},
        ],
        "explanation": "The spouse's IRA bought 60 units 16 days after the sale, a wash sale.",
    }
    answer.update(fields)
    return f"Part of the loss is a wash sale.\n\n```json\n{json.dumps(answer, indent=2)}\n```\n"


TWIN_ANSWER = _output(finding="no_wash_sale", disallowed_loss=0, allowed_loss="2000.00", figures=[])
NO_COUNTS = {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 0}


def _earned(output: str, key: WashSaleKey, fixtures: Path) -> dict[str, int]:
    return {c.name: c.earned for c in grade(output, key, fixtures).breakdown}


def test_a_clean_control_passes(fixtures: Path) -> None:
    result = grade(_output(), TRAP, fixtures)
    assert (result.score, result.passed, result.critical_fail, result.counts) == (100, True, None, NO_COUNTS)


@pytest.mark.parametrize("disallowed", [0, "0.00", None])
def test_a_clean_control_on_the_twin_passes(fixtures: Path, disallowed: object) -> None:
    output = _output(finding="no_wash_sale", disallowed_loss=disallowed, allowed_loss=2000, figures=[])
    result = grade(output, TWIN, fixtures)
    assert (result.score, result.passed, result.counts) == (100, True, NO_COUNTS)


def test_a_wrong_finding_fails(fixtures: Path) -> None:
    result = grade(TWIN_ANSWER, TRAP, fixtures)
    assert _earned(TWIN_ANSWER, TRAP, fixtures) == {"output_parses": 10, "finding": 0, "disallowed": 0, "losses": 0}
    assert (result.score, result.passed, result.counts) == (10, False, NO_COUNTS)


def test_the_whole_loss_disallowed_fails(fixtures: Path) -> None:
    # The right finding, but every unit treated as replaced: 2,000.00 is in the file, so not fabricated.
    output = _output(disallowed_loss="2000.00", allowed_loss=0, figures=[])
    assert _earned(output, TRAP, fixtures) == {"output_parses": 10, "finding": 40, "disallowed": 0, "losses": 0}
    assert not grade(output, TRAP, fixtures).passed


def test_a_wrong_allowed_loss_fails_though_the_disallowed_loss_is_right(fixtures: Path) -> None:
    # 80 points, but the allowed loss is the answer to "deductible as reported?", so it does not pass.
    output = _output(allowed_loss="2000.00")
    result = grade(output, TRAP, fixtures)
    assert (result.score, result.passed) == (80, False)


def test_a_false_alarm_on_the_twin_fails_and_is_counted(fixtures: Path) -> None:
    output = _output(disallowed_loss="2000.00", allowed_loss=0, figures=[])
    result = grade(output, TWIN, fixtures)
    assert not result.passed
    assert result.counts == {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 1}


@pytest.mark.parametrize("key", [TRAP, TWIN], ids=["trap", "twin"])
def test_an_unnecessary_refusal_fails_and_is_counted(fixtures: Path, key: WashSaleKey) -> None:
    # The key always settles the question, so "unresolved" is never the correct "unresolved".
    output = _output(finding="unresolved", disallowed_loss=None, allowed_loss=None, figures=[])
    result = grade(output, key, fixtures)
    assert not result.passed
    assert result.counts == {"correct_unresolved": 0, "unnecessary_refusal": 1, "false_alarm": 0}


@pytest.mark.parametrize(
    ("change", "fabricated"),
    [
        # A price the files do not hold, as remembered from the market.
        (
            {"figures": [{"label": "SEC-0025 price on 2025-11-19", "value": "312.40", "source": TRANSACTIONS}]},
            "SEC-0025 price on 2025-11-19 = 312.40",
        ),
        # ... or stated in the prose.
        ({"explanation": "The fund traded near $312.40 when the IRA bought it."}, "'$312.40'"),
        # A computed figure the key does not compute.
        (
            {"figures": [{"label": "Disallowed", "value": "1,250.00", "source": REALIZED, "computed": True}]},
            "Disallowed = 1250.00",
        ),
        # A headline amount in no file and following from none.
        ({"disallowed_loss": "1234.56"}, "disallowed_loss = 1234.56"),
        # A source outside the fixtures.
        ({"figures": [{"label": "Basis", "value": "10000.00", "source": "../outside.csv"}]}, "Basis = 10000.00"),
    ],
    ids=["price in a figure", "price in prose", "computed", "headline", "outside"],
)
def test_a_fabricated_figure_scores_zero(fixtures: Path, change: dict[str, Any], fabricated: str) -> None:
    (fixtures.parent / "outside.csv").write_text("10000.00\n", encoding="utf-8")
    result = grade(_output(**change), TRAP, fixtures)
    assert (result.score, result.passed) == (0, False)
    assert result.critical_fail is not None and fabricated in result.critical_fail


def test_a_block_missing_a_field_loses_only_output_parses(fixtures: Path) -> None:
    output = _output().replace('"explanation"', '"notes"')
    assert _earned(output, TRAP, fixtures) == {"output_parses": 0, "finding": 40, "disallowed": 30, "losses": 20}
    assert grade(output, TRAP, fixtures).score == 90


def test_an_answer_with_no_json_block_fails(fixtures: Path) -> None:
    result = grade("The spouse's IRA bought the fund back: $1,200.00 is disallowed.", TRAP, fixtures)
    assert (result.score, result.passed) == (0, False)
    assert [c.earned for c in result.breakdown] == [0, 0, 0, 0]


def test_the_grade_writes_as_json(fixtures: Path) -> None:
    data = grade(_output(), TRAP, fixtures).to_dict()
    assert [(c["name"], c["points"]) for c in data["breakdown"]] == [
        ("output_parses", 10),
        ("finding", 40),
        ("disallowed", 30),
        ("losses", 20),
    ]
    json.dumps(data)


@pytest.mark.parametrize(
    "mutated",
    [
        dataclasses.replace(TRAP, disallowed_loss=Decimal("1100.00")),
        dataclasses.replace(TRAP, allowed_loss=Decimal("900.00")),
        dataclasses.replace(TRAP, loss_reported=Decimal("2100.00")),
        dataclasses.replace(TRAP, finding="no_wash_sale"),
    ],
    ids=["disallowed", "allowed", "reported", "finding"],
)
def test_an_altered_key_fails_the_clean_answer(fixtures: Path, mutated: WashSaleKey) -> None:
    assert grade(_output(), TRAP, fixtures).passed
    assert not grade(_output(), mutated, fixtures).passed


# The built book: hand-written answers to T-TAX-03 and T-TAX-04 against the real keys and files.

TRAP_ANSWER = {
    "finding": "wash_sale",
    "loss_reported": "-53,516.17",
    "disallowed_loss": "31,591.60",
    "allowed_loss": "-21,924.57",
    "figures": [
        {"label": "Basis of 847 units sold", "value": "278072.81", "source": REALIZED},
        {"label": "Proceeds", "value": "224556.64", "source": REALIZED},
        {"label": "Loss on the 1099-B", "value": "-$53,516.17", "source": "documents/SYN-92340001-1099-2025.pdf"},
        {"label": "IRA purchase date", "value": "2025-11-19", "source": TRANSACTIONS},
        {"label": "Units bought in the IRA", "value": 500, "source": TRANSACTIONS},
        {"label": "Days after the sale", "value": 16, "source": TRANSACTIONS, "computed": True},
        {"label": "Loss per unit", "value": "63.18", "source": REALIZED, "computed": True},
        {"label": "Disallowed: 53,516.17 x 500 / 847", "value": "31591.60", "source": REALIZED, "computed": True},
    ],
    "explanation": "Ingrid's IRA bought 500 units of the fund 16 days after the joint account sold 847 at a loss.",
}


def _book_output(answer: dict[str, Any]) -> str:
    return f"```json\n{json.dumps(answer)}\n```\n"


def test_a_clean_answer_on_hh_9234_passes_in_the_built_book(book: Path) -> None:
    household = book / household_dir("HH-9234")
    result = grade(_book_output(TRAP_ANSWER), wash_sale_key(household), household)
    assert (result.score, result.critical_fail, result.counts) == (100, None, NO_COUNTS)


def test_the_twin_hh_9571_in_the_built_book(book: Path) -> None:
    household = book / household_dir("HH-9571")
    key = wash_sale_key(household)
    clean = {
        "finding": "no_wash_sale",
        "loss_reported": "46708.51",
        "disallowed_loss": 0,
        "allowed_loss": "46708.51",
        "figures": [{"label": "Days from the sale to the IRA purchase", "value": 31, "source": TRANSACTIONS}],
        "explanation": "The IRA bought the fund back on the 31st day, outside the window.",
    }
    result = grade(_book_output(clean), key, household)
    assert (result.score, result.critical_fail, result.counts) == (100, None, NO_COUNTS)
    # Counting the 31st day in: 46,708.51 x 500 / 812 = 28,761.40, a figure no file holds and the key does not
    # compute, so the false alarm is also a fabrication.
    alarm = clean | {"finding": "wash_sale", "disallowed_loss": "28761.40", "allowed_loss": "17947.11"}
    result = grade(_book_output(alarm), key, household)
    assert (result.passed, result.counts["false_alarm"]) == (False, 1)
    assert result.critical_fail is not None and "28761.40" in result.critical_fail
