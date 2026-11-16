"""The wash-sale key against hand-worked cases and the planted pair of archetype 9 in the built book."""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.keys.wash_sales import UnsettledWashSaleError, WashSaleKey, wash_sale_key
from casebook.model.files import (
    ACCOUNTS_COLUMNS,
    ACCOUNTS_CSV,
    PORTFOLIO_HOUSEHOLD,
    REALIZED_COLUMNS,
    REALIZED_CSV,
    TRANSACTIONS_COLUMNS,
    TRANSACTIONS_CSV,
    csv_text,
    household_dir,
    json_text,
)

JOINT = "SYN-00010001"  # joint taxable, the couple P-1 and P-2
SPOUSE_IRA = "SYN-00010002"  # P-2's traditional IRA
OWN = "SYN-00010003"  # P-1's individual taxable account
DAUGHTER_IRA = "SYN-00010004"  # P-3's IRA; she files on her own
OWN_IRA = "SYN-00010005"  # P-1's traditional IRA
FUND, OTHER = "SEC-0025", "SEC-0027"

ACCOUNTS = {
    JOINT: ("joint_taxable", ["P-1", "P-2"]),
    SPOUSE_IRA: ("traditional_ira", ["P-2"]),
    OWN: ("individual_taxable", ["P-1"]),
    DAUGHTER_IRA: ("roth_ira", ["P-3"]),
    OWN_IRA: ("traditional_ira", ["P-1"]),
}


@dataclass(frozen=True)
class Lot:
    sale: str
    account: str
    lot: str
    units: str
    basis: str
    proceeds: str
    sold: str = "2025-11-03"
    security: str = FUND


@dataclass(frozen=True)
class Acquired:
    transaction: str
    account: str
    day: str
    units: str
    lot: str = ""
    security: str = FUND
    kind: str = "BUY"


def _realized(lot: Lot) -> dict[str, str]:
    gain = Decimal(lot.proceeds) - Decimal(lot.basis)
    return {
        "transaction_id": lot.sale,
        "account_id": lot.account,
        "lot_id": lot.lot,
        "security_id": lot.security,
        "security": "Wexcombe Mid Cap Fund",
        "acquired_date": "2023-07-17",
        "sold_date": lot.sold,
        "units": lot.units,
        "cost_basis": lot.basis,
        "proceeds": lot.proceeds,
        "gain": str(gain),
        "valuation_date": lot.sold,
        "known_as_of": lot.sold,
    }


def _transaction(a: Acquired) -> dict[str, str]:
    row: dict[str, str] = dict.fromkeys(TRANSACTIONS_COLUMNS, "")
    row.update(
        transaction_id=a.transaction,
        account_id=a.account,
        trade_date=a.day,
        settle_date=a.day,
        type=a.kind,
        security_id=a.security,
        security="Wexcombe Mid Cap Fund",
        units=a.units,
        lot_id=a.lot or f"L-E-{a.transaction}",
        price="100.00",
        price_label="synthetic",
        amount="0" if a.kind == "RSU_VEST" else str(-Decimal(a.units) * 100),
        description=f"{a.kind} {a.units}",
        valuation_date=a.day,
        known_as_of=a.day,
    )
    return row


def _dividend(day: str) -> dict[str, str]:
    # A dividend row names the security and its units too, and acquires nothing.
    return _transaction(Acquired("T-DIV", JOINT, day, "100", kind="DIVIDEND")) | {"amount": "250.00", "lot_id": ""}


def _household(root: Path, lots: list[Lot], acquired: list[Acquired]) -> Path:
    accounts = []
    for account, (kind, _) in ACCOUNTS.items():
        row: dict[str, str] = dict.fromkeys(ACCOUNTS_COLUMNS, "")
        row.update(account_id=account, account_type=kind, valuation_date="2026-04-15", known_as_of="2026-04-15")
        accounts.append(row)
    household: dict[str, Any] = {
        "household_id": "HH-0001",
        "legal_ownership": [{"account_id": a, "owner_ids": owners} for a, (_, owners) in ACCOUNTS.items()],
        "household_membership": [
            {"person_id": "P-1", "relationship": "primary"},
            {"person_id": "P-2", "relationship": "spouse"},
            {"person_id": "P-3", "relationship": "daughter"},
        ],
        "tax_units": [{"person_ids": ["P-1", "P-2"]}, {"person_ids": ["P-3"]}],
    }
    files = {
        ACCOUNTS_CSV: csv_text(ACCOUNTS_COLUMNS, accounts),
        REALIZED_CSV: csv_text(REALIZED_COLUMNS, [_realized(lot) for lot in lots]),
        TRANSACTIONS_CSV: csv_text(
            TRANSACTIONS_COLUMNS, [_dividend("2025-11-10")] + [_transaction(a) for a in acquired]
        ),
        PORTFOLIO_HOUSEHOLD: json_text(household),
    }
    for relative, text in files.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(text, encoding="utf-8")
    return root


# 100 units bought for 10,000.00 and sold on 3 November 2025 for 8,000.00: a loss of 2,000.00, 20.00 a unit.
SALE = Lot("T-1", JOINT, "L-OLD", "100", "10000.00", "8000.00")


def _key(root: Path, lots: list[Lot], acquired: list[Acquired]) -> WashSaleKey:
    return wash_sale_key(_household(root, lots, acquired))


def _amounts(key: WashSaleKey) -> tuple[str, Decimal, Decimal, Decimal]:
    return key.finding, key.loss_reported, key.disallowed_loss, key.allowed_loss


def test_a_purchase_in_the_spouses_ira_within_30_days_disallows_the_replaced_units_share(tmp_path: Path) -> None:
    # 60 of the 100 units replaced 16 days later: 2,000.00 x 60 / 100 = 1,200.00 disallowed, 800.00 allowed.
    key = _key(tmp_path, [SALE], [Acquired("T-2", SPOUSE_IRA, "2025-11-19", "60")])
    assert _amounts(key) == ("wash_sale", Decimal("2000.00"), Decimal("1200.00"), Decimal("800.00"))
    (lot,) = key.washed
    assert [(r.transaction_id, r.account_type, r.days_from_sale, r.units) for r in lot.replacements] == [
        ("T-2", "traditional_ira", 16, Decimal("60"))
    ]


def test_more_units_bought_than_sold_disallow_the_whole_loss(tmp_path: Path) -> None:
    key = _key(tmp_path, [SALE], [Acquired("T-2", SPOUSE_IRA, "2025-11-19", "250")])
    assert _amounts(key) == ("wash_sale", Decimal("2000.00"), Decimal("2000.00"), Decimal("0.00"))


@pytest.mark.parametrize(
    ("day", "washed"),
    [
        ("2025-12-03", True),  # 3 November + 30 days: the last day of the window
        ("2025-12-04", False),  # the 31st day after: outside
        ("2025-10-04", True),  # 30 days before
        ("2025-10-03", False),  # 31 days before
        ("2025-11-03", True),  # the day of the sale
    ],
)
def test_the_window_is_30_days_either_side_of_the_sale(tmp_path: Path, day: str, washed: bool) -> None:
    key = _key(tmp_path, [SALE], [Acquired("T-2", SPOUSE_IRA, day, "60")])
    assert key.disallowed_loss == (Decimal("1200.00") if washed else Decimal("0.00"))
    assert key.finding == ("wash_sale" if washed else "no_wash_sale")


@pytest.mark.parametrize(
    ("acquired", "disallowed"),
    [
        # The seller's own IRA counts (Rev. Rul. 2008-5): 2,000.00 x 60 / 100.
        (Acquired("T-2", OWN_IRA, "2025-11-19", "60"), "1200.00"),
        # So does an RSU release into the seller's own taxable account.
        (Acquired("T-2", OWN, "2025-11-19", "60", kind="RSU_VEST"), "1200.00"),
        # The daughter files on her own and is not a spouse: her purchase replaces nothing.
        (Acquired("T-2", DAUGHTER_IRA, "2025-11-19", "60"), "0.00"),
        # A different security replaces nothing.
        (Acquired("T-2", SPOUSE_IRA, "2025-11-19", "60", security=OTHER), "0.00"),
    ],
    ids=["own IRA", "RSU release", "a daughter filing apart", "another security"],
)
def test_whose_acquisition_counts(tmp_path: Path, acquired: Acquired, disallowed: str) -> None:
    assert _key(tmp_path, [SALE], [acquired]).disallowed_loss == Decimal(disallowed)


def test_shares_bought_and_sold_in_the_same_sale_replace_nothing(tmp_path: Path) -> None:
    # 40 units bought on 20 October at 85.00 (3,400.00) are sold with the old 100 on 3 November at 80.00:
    # the old lot loses 2,000.00 and the new one 3,400.00 - 3,200.00 = 200.00. The purchase is in the window
    # but none of it is left over to replace anything, so the whole 2,200.00 is allowed.
    lots = [SALE, Lot("T-1", JOINT, "L-E-T-2", "40", "3400.00", "3200.00")]
    key = _key(tmp_path, lots, [Acquired("T-2", JOINT, "2025-10-20", "40")])
    assert _amounts(key) == ("no_wash_sale", Decimal("2200.00"), Decimal("0.00"), Decimal("2200.00"))


def test_shares_bought_and_kept_through_the_sale_still_replace(tmp_path: Path) -> None:
    # The same 40 bought on 20 October, but the sale takes only 30 of them (2,550.00 basis, 2,400.00
    # proceeds: a 150.00 loss). The 10 kept replace 10 of the units sold, matched to the lots in the order
    # sold: the old lot first, 2,000.00 x 10 / 100 = 200.00 disallowed. Losses 2,150.00; allowed 1,950.00.
    lots = [SALE, Lot("T-1", JOINT, "L-E-T-2", "30", "2550.00", "2400.00")]
    key = _key(tmp_path, lots, [Acquired("T-2", JOINT, "2025-10-20", "40")])
    assert _amounts(key) == ("wash_sale", Decimal("2150.00"), Decimal("200.00"), Decimal("1950.00"))
    assert [(lot.lot_id, lot.disallowed) for lot in key.loss_lots] == [
        ("L-OLD", Decimal("200.00")),
        ("L-E-T-2", Decimal("0.00")),
    ]


def test_each_replacement_unit_is_matched_once_in_the_order_sold(tmp_path: Path) -> None:
    # The joint sale of 100 (loss 2,000.00) on 3 November, then P-1's own sale of 50 for a 500.00 loss
    # (5,000.00 basis, 4,500.00 proceeds) on 10 November; the spouse's IRA buys 120 on 19 November. The first
    # sale takes 100 units (2,000.00 disallowed), the second the 20 left: 500.00 x 20 / 50 = 200.00.
    later = Lot("T-3", OWN, "L-OWN", "50", "5000.00", "4500.00", sold="2025-11-10")
    key = _key(tmp_path, [later, SALE], [Acquired("T-2", SPOUSE_IRA, "2025-11-19", "120")])
    assert _amounts(key) == ("wash_sale", Decimal("2500.00"), Decimal("2200.00"), Decimal("300.00"))
    assert [(lot.transaction_id, lot.units_replaced, lot.disallowed) for lot in key.loss_lots] == [
        ("T-1", Decimal("100"), Decimal("2000.00")),
        ("T-3", Decimal("20"), Decimal("200.00")),
    ]


@pytest.mark.parametrize(
    "lot",
    [
        Lot("T-1", JOINT, "L-OLD", "100", "8000.00", "10000.00"),  # a gain
        Lot("T-1", OWN_IRA, "L-OLD", "100", "10000.00", "8000.00"),  # a loss inside an IRA
        Lot("T-1", JOINT, "L-OLD", "100", "10000.00", "8000.00", sold="2026-01-05"),  # a 2026 sale
    ],
    ids=["gain", "IRA", "2026"],
)
def test_only_2025_losses_in_taxable_accounts_are_reviewed(tmp_path: Path, lot: Lot) -> None:
    key = _key(tmp_path, [lot], [Acquired("T-2", SPOUSE_IRA, lot.sold, "60")])
    assert (key.finding, key.loss_lots) == ("no_wash_sale", ())


def test_a_sale_whose_window_starts_before_the_transactions_is_refused(tmp_path: Path) -> None:
    early = Lot("T-1", JOINT, "L-OLD", "100", "10000.00", "8000.00", sold="2025-01-20")
    with pytest.raises(UnsettledWashSaleError, match="not on file"):
        _key(tmp_path, [early], [])


def test_the_key_lists_the_figures_an_answer_derives(tmp_path: Path) -> None:
    key = _key(tmp_path, [SALE], [Acquired("T-2", SPOUSE_IRA, "2025-12-04", "60")])
    values = {f.label: f.value for f in key.computed_figures}
    assert values["T-1 lot L-OLD loss per unit"] == Decimal("20.0000")
    assert values["days from T-1 to T-2"] == Decimal(31)
    assert values["allowed loss"] == Decimal("2000.00")
    data = key.to_dict()
    assert (data["finding"], data["disallowed_loss"], data["loss_lots"][0]["replacements"]) == (
        "no_wash_sale",
        "0.00",
        [],
    )


@pytest.mark.parametrize("build", ["book", "real_book"])
def test_the_trap_hh_9234_loses_the_replaced_share_of_its_loss(request: pytest.FixtureRequest, build: str) -> None:
    # T-9234-0035 sold 847 units of SEC-0025 from the joint account SYN-92340001 on 3 November 2025:
    # basis 278,072.81 - proceeds 224,556.64 = a loss of 53,516.17. T-9234-0037: Ingrid's traditional IRA
    # SYN-92340002 bought 500 units on 19 November, 16 days later. 53,516.17 x 500 / 847 = 26,758,085.00 / 847
    # = 31,591.5998..., so 31,591.60 disallowed and 53,516.17 - 31,591.60 = 21,924.57 allowed.
    book: Path = request.getfixturevalue(build)
    key = wash_sale_key(book / household_dir("HH-9234"))
    assert _amounts(key) == ("wash_sale", Decimal("53516.17"), Decimal("31591.60"), Decimal("21924.57"))
    (lot,) = key.washed
    assert (lot.transaction_id, lot.units, lot.units_replaced) == ("T-9234-0035", Decimal("847"), Decimal("500"))
    assert [(r.transaction_id, r.account_id, r.days_from_sale) for r in lot.replacements] == [
        ("T-9234-0037", "SYN-92340002", 16)
    ]


@pytest.mark.parametrize("build", ["book", "real_book"])
def test_the_twin_hh_9571_keeps_its_whole_loss(request: pytest.FixtureRequest, build: str) -> None:
    # T-9571-0035 sold 812 units of SEC-0025 on 3 November 2025: 261,985.95 - 215,277.44 = 46,708.51 lost.
    # Elena's IRA bought 500 units on 4 December (T-9571-0037): November has 30 days, so that is day 31.
    book: Path = request.getfixturevalue(build)
    key = wash_sale_key(book / household_dir("HH-9571"))
    assert _amounts(key) == ("no_wash_sale", Decimal("46708.51"), Decimal("0.00"), Decimal("46708.51"))
    assert {f.label: f.value for f in key.computed_figures}["days from T-9571-0035 to T-9571-0037"] == Decimal(31)
