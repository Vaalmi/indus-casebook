"""The loss-harvesting key behind a compliance review of a household's 2025 loss harvesting: the wash-sale key's
losses on archetype 9's featured pair, and one issue per loss sale a purchase replaced."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from casebook.keys.issues import Issue
from casebook.keys.loss_harvesting import LossHarvestingKey, loss_harvesting_key
from casebook.keys.wash_sales import LossLot, Replacement, WashSaleKey
from casebook.model.files import household_dir


def test_the_trap_raises_the_sale_its_spouse_s_ira_replaced(book: Path) -> None:
    key = loss_harvesting_key(book / household_dir("HH-9234"))
    assert key.finding == "issues_found"
    # The joint account SYN-92340001 sold 847 units of SEC-0025 on 3 November 2025 (T-9234-0035): basis
    # 278,072.81, proceeds 224,556.64, a loss of 53,516.17. Ingrid's IRA SYN-92340002 bought 500 units on
    # 19 November (T-9234-0037), 16 days later: 53,516.17 x 500 / 847 = 31,591.60 disallowed, 21,924.57 allowed.
    assert (key.wash_sales.loss_reported, key.wash_sales.disallowed_loss, key.wash_sales.allowed_loss) == (
        Decimal("53516.17"),
        Decimal("31591.60"),
        Decimal("21924.57"),
    )
    assert key.issues == (Issue("loss on T-9234-0035 replaced within the window", ("T-9234-0035", "T-9234-0037")),)
    assert key.to_dict()["issues"] == [
        {"issue": "loss on T-9234-0035 replaced within the window", "records": ["T-9234-0035", "T-9234-0037"]}
    ]


def test_the_near_miss_twin_has_nothing_to_raise(book: Path) -> None:
    key = loss_harvesting_key(book / household_dir("HH-9571"))
    # SYN-95710001 sold 812 units of SEC-0025 on 3 November 2025 at a loss of 261,985.95 - 215,277.44 = 46,708.51;
    # the IRA bought it back on 4 December (T-9571-0037), 31 days later, outside the window.
    assert (key.finding, key.issues) == ("no_issues", ())
    assert (key.wash_sales.loss_reported, key.wash_sales.disallowed_loss) == (Decimal("46708.51"), Decimal("0.00"))
    assert key.to_dict()["finding"] == "no_issues"


def _lot(lot_id: str, buy: str) -> LossLot:
    replaced = Replacement(buy, "SYN-00010002", "traditional_ira", date(2025, 11, 19), 16, Decimal(10))
    return LossLot(
        "T-1", "SYN-00010001", lot_id, "SEC-0025", date(2023, 7, 17), date(2025, 11, 3), Decimal(10),
        Decimal("1000.00"), Decimal("800.00"), (replaced,), Decimal("200.00"),
    )  # fmt: skip


def test_one_sale_that_closed_two_replaced_lots_is_one_issue() -> None:
    lots = (_lot("L-1", "T-2"), _lot("L-2", "T-3"))
    wash = WashSaleKey("HH-0001", "wash_sale", Decimal("400.00"), Decimal("400.00"), Decimal(0), lots, ())
    assert LossHarvestingKey(wash).issues == (Issue("loss on T-1 replaced within the window", ("T-1", "T-2", "T-3")),)
