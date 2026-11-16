"""The six checks slice 3 adds: a seeded defect makes each fail, naming the household, line and account, lot or file."""

import csv
import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from .test_checks import HH, edit_csv_cell, failures, household

TWIN = "HH-7350"


def problems(book: Path, check: str, hh: str = HH) -> tuple[str, ...]:
    return failures(book).get((hh, check), ())


def add_registry_entry(book: Path, item_type: str, sources: list[str], refs: list[str], hh: str = HH) -> None:
    path = book / "sealed" / "registry.json"
    registry = json.loads(path.read_text())
    registry["entries"].append(
        {
            "item_id": "PI-TEST",
            "household_id": hh,
            "kind": "situation",
            "type": item_type,
            "title": "A test entry",
            "sources": sources,
            "justified_conclusion": "Planted for the test.",
            "figures": [],
            "table": {"columns": [], "rows": []},
            "references": refs,
        }
    )
    path.write_text(json.dumps(registry))


def edit_json(path: Path, change: Callable[[Any], object]) -> None:
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


# Prices and values


def test_a_second_price_for_a_security_on_a_date_fails_the_prices_check(book_copy: Path) -> None:
    path = household(book_copy) / "custodian" / "positions.csv"
    match = {"account_id": "SYN-48210002", "security_id": "SEC-0003", "valuation_date": "2025-09-30"}
    line = edit_csv_cell(path, match, "price", "1.00")
    found = problems(book_copy, "prices and values")
    assert any(
        p.startswith(f"custodian/positions.csv line {line}: SEC-0003 on 2025-09-30 is priced 1.00;") for p in found
    )
    assert any(f"custodian/positions.csv line {line}: SYN-48210002 SEC-0003 value" in p for p in found)


# Lots and basis


def test_a_sale_of_more_than_the_lot_holds_fails_as_oversold(book_copy: Path) -> None:
    path = household(book_copy) / "custodian" / "realized_lots.csv"
    line = edit_csv_cell(path, {"lot_id": "L-48210001-04"}, "units", "5000")
    found = problems(book_copy, "lots and basis")
    assert any(
        f"custodian/realized_lots.csv line {line}: lot L-48210001-04 in SYN-48210001 is oversold" in p for p in found
    )


def test_a_closing_lot_whose_basis_did_not_roll_forward_fails(book_copy: Path) -> None:
    path = household(book_copy) / "custodian" / "tax_lots.csv"
    line = edit_csv_cell(path, {"lot_id": "L-48210003-01", "valuation_date": "2026-04-15"}, "cost_basis", "1.00")
    found = problems(book_copy, "lots and basis")
    assert any(
        p.startswith(f"custodian/tax_lots.csv line {line}: lot L-48210003-01 is ") and "basis 1.00" in p for p in found
    )


# Wash sales


def plant_wash_sale(book: Path, buyer: str, day: str) -> None:
    """Turn the joint account's 2025-09-08 sale into a loss (proceeds 100.00) and add a purchase on `day`."""
    root = household(book)
    realized = root / "custodian" / "realized_lots.csv"
    with realized.open(newline="") as handle:
        cost = Decimal(next(r for r in csv.DictReader(handle) if r["lot_id"] == "L-48210001-04")["cost_basis"])
    edit_csv_cell(realized, {"lot_id": "L-48210001-04"}, "proceeds", "100.00")
    edit_csv_cell(realized, {"lot_id": "L-48210001-04"}, "gain", str(Decimal("100.00") - cost))
    buy = (
        f"T-4821-9999,{buyer},{day},{day},BUY,SEC-0004,Orrin Software Group,10,L-E-4821-9999,200.00,synthetic,"
        f"-2000.00,Buy 10 Orrin Software Group,{day},{day}\n"
    )
    path = root / "custodian" / "transactions.csv"
    path.write_text(path.read_text() + buy)


def test_a_loss_sale_with_a_repurchase_in_the_spouses_ira_fails_the_wash_sale_check(book_copy: Path) -> None:
    # The sale was in the joint account on 2025-09-08; Henrik's IRA buys the same security 12 days later.
    plant_wash_sale(book_copy, "SYN-48210002", "2025-09-20")
    found = problems(book_copy, "wash sales")
    assert len(found) == 1
    assert found[0].startswith("custodian/realized_lots.csv line 2: a loss on SEC-0004 in SYN-48210001 on 2025-09-08")
    assert "buys it in SYN-48210002 on 2025-09-20, with no registry entry for the wash sale" in found[0]


def test_a_registered_wash_sale_passes(book_copy: Path) -> None:
    plant_wash_sale(book_copy, "SYN-48210002", "2025-09-20")
    sources = ["custodian/realized_lots.csv", "custodian/transactions.csv"]
    add_registry_entry(book_copy, "wash_sale", sources, ["T-4821-0031", "T-4821-9999"])
    assert problems(book_copy, "wash sales") == ()


def test_a_repurchase_outside_the_tax_unit_or_the_window_is_no_wash_sale(book_copy: Path) -> None:
    plant_wash_sale(book_copy, "SYN-48210003", "2025-09-20")  # Ngozi files her own return
    assert problems(book_copy, "wash sales") == ()


def test_a_repurchase_31_days_later_is_no_wash_sale(book_copy: Path) -> None:
    plant_wash_sale(book_copy, "SYN-48210002", "2025-10-09")
    assert problems(book_copy, "wash sales") == ()


def test_a_repurchase_30_days_before_is_a_wash_sale(book_copy: Path) -> None:
    plant_wash_sale(book_copy, "SYN-48210002", "2025-08-09")
    assert len(problems(book_copy, "wash sales")) == 1


# Carry-in history


def test_missing_ira_basis_and_loss_carryforward_fail_the_carry_in_check(book_copy: Path) -> None:
    def drop(data: dict[str, Any]) -> None:
        data["ira_basis"] = []
        data["loss_carryforwards"] = data["loss_carryforwards"][:1]

    edit_json(household(book_copy) / "portfolio" / "tax_profile.json", drop)
    assert problems(book_copy, "carry-in history") == (
        "portfolio/tax_profile.json: tax unit TU-4821-2 has no loss carryforward",
        "portfolio/tax_profile.json: IRA owner P-4821-2 has no IRA basis",
    )


def test_opening_positions_without_opening_lots_fail_the_carry_in_check(book_copy: Path) -> None:
    path = household(book_copy) / "custodian" / "tax_lots.csv"
    lines = path.read_text().splitlines()
    kept = [line for line in lines if not (line.startswith("SYN-48210003,") and line.endswith("2024-12-31,2024-12-31"))]
    path.write_text("\n".join(kept) + "\n")
    found = problems(book_copy, "carry-in history")
    assert any("SYN-48210003 SEC-0001 has no opening lots, so its acquisition dates are missing" in p for p in found)


# Sources agree


def test_custodian_and_portfolio_holdings_that_differ_fail_with_both_files_named(book_copy: Path) -> None:
    edit_json(household(book_copy) / "portfolio" / "positions.json", lambda d: d["positions"][0].update(units="1"))
    found = problems(book_copy, "sources agree")
    assert any(
        p.startswith(
            "custodian/positions.csv and portfolio/positions.json disagree with no registry entry: SYN-48210001"
        )
        for p in found
    )


def test_the_householding_disagreement_passes_only_with_its_registry_entry(book_copy: Path) -> None:
    assert problems(book_copy, "sources agree") == ()
    edit_json(book_copy / "sealed" / "registry.json", lambda d: d.update(entries=[]))
    assert problems(book_copy, "sources agree") == (
        "crm/crm.json and portfolio/household.json disagree with no registry entry: householding agreement "
        "AGR-4821-3 joins SYN-48210001, SYN-48210002, SYN-48210003, which the billing groups keep apart",
    )


def test_a_statement_total_that_differs_from_the_custodian_fails(book_copy: Path) -> None:
    path = household(book_copy) / "custodian" / "positions.csv"
    match = {"account_id": "SYN-48210002", "security_id": "SEC-0001", "valuation_date": "2026-03-31"}
    edit_csv_cell(path, match, "market_value", "1.00")
    found = problems(book_copy, "sources agree")
    assert any(
        p.startswith("documents/statement-SYN-48210002-2026Q1.pdf and custodian/positions.csv disagree") for p in found
    )


def test_custodian_owners_that_differ_from_legal_ownership_fail(book_copy: Path) -> None:
    edit_csv_cell(
        household(book_copy) / "custodian" / "accounts.csv", {"account_id": "SYN-48210003"}, "owners", "Ngozi Okafor"
    )
    found = problems(book_copy, "sources agree")
    assert found == (
        "custodian/accounts.csv and portfolio/household.json disagree with no registry entry: "
        "SYN-48210003 owners ['Ngozi Okafor']",
    )


# Background thresholds


def make_background(book: Path, hh: str = HH) -> None:
    edit_json(
        book / "sealed" / "households.json",
        lambda d: [h.update(set="background") for h in d["households"] if h["household_id"] == hh],
    )


def test_a_featured_household_is_not_held_to_the_background_thresholds(book_copy: Path) -> None:
    assert problems(book_copy, "background thresholds") == ()


def test_a_background_household_over_its_concentration_limit_fails_until_registered(book_copy: Path) -> None:
    make_background(book_copy)
    found = problems(book_copy, "background thresholds")
    assert any(p.startswith("crosses a concentration threshold with no registry entry: SEC-0001 is ") for p in found)
    add_registry_entry(book_copy, "concentration", ["custodian/positions.csv", "portfolio/ips.json"], ["SEC-0001"])
    # The entry names SEC-0001 only; the bond fund, also above the limit, still fails.
    remaining = [p for p in problems(book_copy, "background thresholds") if "concentration" in p]
    assert remaining and not any("SEC-0001" in p for p in remaining)


def test_a_background_ira_owner_past_rmd_age_with_no_distribution_fails(book_copy: Path) -> None:
    make_background(book_copy, TWIN)
    path = book_copy / "households" / TWIN / "portfolio" / "household.json"
    edit_json(
        path, lambda d: [m.update(born="1950-01-27") for m in d["household_membership"] if m["person_id"] == "P-7350-2"]
    )
    found = problems(book_copy, "background thresholds", TWIN)
    expected = "SYN-73500002 owes a 2025 distribution and shows none by 2026-04-01"
    assert f"crosses a rmd threshold with no registry entry: {expected}" in found


# Reviewer B, slice 3 round 1


def test_a_duplicate_row_in_the_book_price_series_fails_the_prices_check(book_copy: Path) -> None:
    # S1: duplicate keys were folded together before the check saw them.
    path = book_copy / "securities" / "prices_synthetic.csv"
    lines = path.read_text().splitlines()
    first = lines[1].split(",")
    first[3] = "0.01"
    lines.insert(1, ",".join(first))
    path.write_text("\n".join(lines) + "\n")
    found = problems(book_copy, "prices and values")
    assert any(p.startswith("securities/prices_synthetic.csv line 3: SEC-0001 on 2024-12-31 is priced") for p in found)


def test_carried_in_entries_without_amounts_fail_the_carry_in_check(book_copy: Path) -> None:
    # S2: an entry with its identifiers and no amounts passed.
    def strip(data: dict[str, Any]) -> None:
        for entry in data["loss_carryforwards"]:
            entry.pop("short_term")
        data["ira_basis"][0].pop("basis")

    edit_json(household(book_copy) / "portfolio" / "tax_profile.json", strip)
    found = problems(book_copy, "carry-in history")
    assert "portfolio/tax_profile.json: tax unit TU-4821-1's loss carryforward has no short_term amount" in found
    assert "portfolio/tax_profile.json: IRA owner P-4821-2 has no basis amount" in found


def test_a_portfolio_system_with_no_cash_lines_disagrees_with_the_custodian(book_copy: Path) -> None:
    # S3: only cash lines present in the portfolio file were compared.
    edit_json(household(book_copy) / "portfolio" / "positions.json", lambda d: d.update(cash=[]))
    found = problems(book_copy, "sources agree")
    assert any(p.endswith("SYN-48210001 cash 48634.39 and no cash line") or "SYN-48210001 cash" in p for p in found)
    assert all(p.startswith("custodian/cash.csv and portfolio/positions.json disagree") for p in found)


def test_shares_kept_from_a_purchase_partly_sold_at_a_loss_are_a_wash_sale(book_copy: Path) -> None:
    # S4: buy 100 on 2025-09-01, sell 50 of that lot at a loss on 2025-09-08; the 50 kept replace them.
    root = household(book_copy)
    buy = (
        "T-4821-9998,SYN-48210001,2025-09-01,2025-09-02,BUY,SEC-0004,Orrin Software Group,100,L-E-4821-9998,"
        "215.00,synthetic,-21500.00,Buy 100 Orrin Software Group,2025-09-01,2025-09-01\n"
    )
    path = root / "custodian" / "transactions.csv"
    path.write_text(path.read_text() + buy)
    realized = root / "custodian" / "realized_lots.csv"
    for column, value in (
        ("lot_id", "L-E-4821-9998"),
        ("units", "50"),
        ("cost_basis", "10750.00"),
        ("proceeds", "10500.00"),
    ):
        edit_csv_cell(realized, {"transaction_id": "T-4821-0031"}, column, value)
    found = problems(book_copy, "wash sales")
    assert len(found) == 1 and "buys it in SYN-48210001 on 2025-09-01" in found[0]


def test_a_gain_that_does_not_follow_from_proceeds_and_basis_fails_and_hides_no_wash_sale(book_copy: Path) -> None:
    # D1: a loss sale with a positive gain column hid a wash sale.
    plant_wash_sale(book_copy, "SYN-48210002", "2025-09-20")
    realized = household(book_copy) / "custodian" / "realized_lots.csv"
    edit_csv_cell(realized, {"lot_id": "L-48210001-04"}, "gain", "1.00")
    assert len(problems(book_copy, "wash sales")) == 1
    assert any("gain 1.00 is not proceeds 100.00 less basis" in p for p in problems(book_copy, "lots and basis"))


# Reviewer A, slice 3 round 1


def test_a_registered_wash_sale_does_not_excuse_another(book_copy: Path) -> None:
    # S2: one wash-sale entry excused every wash sale in the household.
    plant_wash_sale(book_copy, "SYN-48210002", "2025-09-20")
    sources = ["custodian/realized_lots.csv", "custodian/transactions.csv"]
    add_registry_entry(book_copy, "wash_sale", sources, ["T-4821-0031", "T-4821-0001"])
    assert len(problems(book_copy, "wash sales")) == 1


def test_a_spouses_purchase_is_a_wash_sale_when_they_file_apart(book_copy: Path) -> None:
    # S3: spouses counted only through a shared tax unit.
    def apart(data: dict[str, Any]) -> None:
        data["legal_ownership"][0]["owner_ids"] = ["P-4821-1"]
        data["tax_units"] = [
            {"tax_unit_id": "TU-4821-1", "filing_status": "married_filing_separately", "person_ids": ["P-4821-1"]},
            {"tax_unit_id": "TU-4821-3", "filing_status": "married_filing_separately", "person_ids": ["P-4821-2"]},
            {"tax_unit_id": "TU-4821-2", "filing_status": "single", "person_ids": ["P-4821-3"]},
        ]

    edit_json(household(book_copy) / "portfolio" / "household.json", apart)
    plant_wash_sale(book_copy, "SYN-48210002", "2025-09-20")
    assert len(problems(book_copy, "wash sales")) == 1


def test_statement_holdings_that_differ_from_the_custodian_fail(book_copy: Path) -> None:
    # S6: only the statement's total was compared.
    path = household(book_copy) / "custodian" / "positions.csv"
    match = {"account_id": "SYN-48210002", "security_id": "SEC-0003", "valuation_date": "2026-03-31"}
    edit_csv_cell(path, match, "units", "1")
    found = problems(book_copy, "sources agree")
    assert any(
        p.startswith("documents/statement-SYN-48210002-2026Q1.pdf and custodian/positions.csv disagree")
        and "SYN-48210002 SEC-0003 on 2026-03-31: the statement shows 1374 units" in p
        for p in found
    )


def test_a_zero_distribution_does_not_meet_an_rmd(book_copy: Path) -> None:
    # S7: a zero-dollar distribution cleared the missing-RMD failure.
    make_background(book_copy, TWIN)
    path = book_copy / "households" / TWIN / "portfolio" / "household.json"
    edit_json(
        path, lambda d: [m.update(born="1950-01-27") for m in d["household_membership"] if m["person_id"] == "P-7350-2"]
    )
    transactions = book_copy / "households" / TWIN / "custodian" / "transactions.csv"
    zero = (
        "T-7350-9999,SYN-73500002,2025-12-31,2025-12-31,DISTRIBUTION,,,,,,,0.00,"
        "Required minimum distribution for 2025,2025-12-31,2025-12-31\n"
    )
    transactions.write_text(transactions.read_text() + zero)
    assert any("SYN-73500002 owes a 2025 distribution" in p for p in problems(book_copy, "background thresholds", TWIN))


def test_a_cash_transfer_needs_no_units(book_copy: Path) -> None:
    # D1: a valid cash transfer failed the units check for blank units.
    transactions = household(book_copy) / "custodian" / "transactions.csv"
    rows = (
        "T-4821-9997,SYN-48210001,2026-04-10,2026-04-10,TRANSFER_OUT,,,,,,,-500.00,Cash transfer to SYN-48210003,"
        "2026-04-10,2026-04-10\n"
        "T-4821-9997,SYN-48210003,2026-04-10,2026-04-10,TRANSFER_IN,,,,,,,500.00,Cash transfer from SYN-48210001,"
        "2026-04-10,2026-04-10\n"
    )
    transactions.write_text(transactions.read_text() + rows)
    assert not any("has no units" in p for p in problems(book_copy, "units"))


# Reviewers A and B, slice 3 round 2


def test_a_statement_price_that_differs_from_the_custodian_fails(book_copy: Path) -> None:
    # A-S6 held, B-S5: the statement's printed price was read and thrown away.
    path = household(book_copy) / "custodian" / "positions.csv"
    match = {"account_id": "SYN-48210002", "security_id": "SEC-0003", "valuation_date": "2026-03-31"}
    edit_csv_cell(path, match, "price", "1.00")
    found = problems(book_copy, "sources agree")
    assert any(
        "SYN-48210002 SEC-0003 on 2026-03-31: the statement shows 1374 units at" in p and "at 1.00" in p for p in found
    )


def test_statement_cash_that_differs_from_the_custodian_fails(book_copy: Path) -> None:
    # A-S6 held: the statement's cash line was not compared.
    path = household(book_copy) / "custodian" / "cash.csv"
    edit_csv_cell(path, {"account_id": "SYN-48210002", "valuation_date": "2026-03-31"}, "settled_cash", "1.00")
    found = problems(book_copy, "sources agree")
    assert any(
        p.startswith("documents/statement-SYN-48210002-2026Q1.pdf and custodian/cash.csv disagree")
        and "SYN-48210002 cash on 2026-03-31: the statement shows 6815.97, the custodian 1.00" in p
        for p in found
    )


def test_shares_sold_before_the_loss_sale_replace_nothing(book_copy: Path) -> None:
    # A-D2: buy 10, sell 5 at a gain, then the other 5 at a loss: nothing of the purchase is left to replace them.
    root = household(book_copy)
    transactions = root / "custodian" / "transactions.csv"
    transactions.write_text(
        transactions.read_text()
        + "T-4821-9990,SYN-48210003,2025-01-09,2025-01-10,BUY,SEC-0004,Orrin Software Group,10,L-E-4821-9990,"
        "212.08,synthetic,-2120.80,Buy 10 Orrin Software Group,2025-01-09,2025-01-09\n"
    )
    realized = root / "custodian" / "realized_lots.csv"
    realized.write_text(
        realized.read_text()
        + "T-4821-9991,SYN-48210003,L-E-4821-9990,SEC-0004,Orrin Software Group,2025-01-09,2025-01-15,5,1060.40,"
        "1062.15,1.75,2025-01-15,2025-01-15\n"
        + "T-4821-9992,SYN-48210003,L-E-4821-9990,SEC-0004,Orrin Software Group,2025-01-09,2025-01-16,5,1060.40,"
        "1053.00,-7.40,2025-01-16,2025-01-16\n"
    )
    assert problems(book_copy, "wash sales") == ()
