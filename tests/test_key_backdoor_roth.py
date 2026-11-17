"""The backdoor Roth key: Form 8606 on hand-built households, on the featured pair of archetype 1 on both
builds, and on every archetype 1 pair in the whole book against the planters' figures."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from casebook.keys.backdoor_roth import UnsettledBackdoorError, backdoor_conversions, backdoor_roth_key
from casebook.model.files import PORTFOLIO_TAX_PROFILE, REGISTRY, SEALED_HOUSEHOLDS, household_dir, json_text

from .test_key_rmd import A, B, C, account, cash, payout, position, write_household

YEAR_END = "2025-12-31"


def household(
    root: Path, pre_tax_kind: str = "traditional_ira", basis: str = "0.00", year_end_cash: bool = True
) -> Path:
    """P-1 contributes 7,000.00 to the new traditional IRA A on 10 February 2025 and converts 7,000.00 to the
    Roth IRA C three days later; A is empty on 31 December 2025. B holds 90,000.00 of funds and 3,000.00 of
    cash that day: a rollover IRA, or a 401(k) when `pre_tax_kind` says so."""
    write_household(
        root,
        {"P-1": "1980-03-01"},
        [(account(A, "traditional_ira"), "P-1"), (account(B, pre_tax_kind), "P-1"), (account(C, "roth_ira"), "P-1")],
        [position(B, "90000.00", YEAR_END)],
        [cash(A, "0.00", YEAR_END), cash(C, "500.00", YEAR_END)]
        + ([cash(B, "3000.00", YEAR_END)] if year_end_cash else []),
        [
            payout("T-1", A, "2025-02-10", "CONTRIBUTION", "7000.00"),
            payout("T-2", A, "2025-02-13", "CONVERSION_OUT", "-7000.00"),
            payout("T-2", C, "2025-02-13", "CONVERSION_IN", "7000.00"),
            payout("T-3", B, "2025-03-25", "DIVIDEND", "400.00"),
        ],
    )
    (root / PORTFOLIO_TAX_PROFILE).write_text(json_text({"ira_basis": [{"person_id": "P-1", "basis": basis}]}))
    return root


def test_a_rollover_ira_makes_most_of_the_conversion_taxable(tmp_path: Path) -> None:
    key = backdoor_roth_key(household(tmp_path))
    form = key.backdoor.form
    # Line 6: A 0.00 + B 90,000.00 + 3,000.00 = 93,000.00. Line 9: 93,000.00 + 0 + 7,000.00 = 100,000.00.
    # Line 10: 7,000.00 / 100,000.00 = 0.070. Line 11: 7,000.00 x 0.070 = 490.00, nontaxable.
    # Line 18: 7,000.00 - 490.00 = 6,510.00 taxable. Line 14: 7,000.00 - 490.00 = 6,510.00 carried to 2026.
    assert (form.line_6, form.line_9, form.line_10) == (Decimal("93000.00"), Decimal("100000.00"), Decimal("0.070"))
    assert (form.line_11, form.line_18, form.line_14) == (Decimal("490.00"), Decimal("6510.00"), Decimal("6510.00"))
    assert (key.finding, key.taxable_amount, key.basis_carried) == (
        "pro_rata_tax",
        Decimal("6510.00"),
        Decimal("6510.00"),
    )
    assert key.backdoor.pre_tax_iras == (B,)
    assert (key.backdoor.contribution_ids, key.backdoor.conversion_ids) == (("T-1",), ("T-2",))


def test_pre_tax_money_in_a_401k_leaves_the_conversion_tax_free(tmp_path: Path) -> None:
    key = backdoor_roth_key(household(tmp_path, pre_tax_kind="401k"))
    # Line 6 counts only A, empty: line 9 is 7,000.00, line 10 is 1.000, line 11 is 7,000.00, nothing taxable.
    form = key.backdoor.form
    assert (form.line_6, form.line_10, form.line_17) == (Decimal("0.00"), Decimal("1.000"), Decimal("7000.00"))
    assert (key.finding, key.taxable_amount, key.basis_carried) == ("no_pro_rata_tax", Decimal(0), Decimal("0.00"))


def test_basis_carried_in_raises_the_nontaxable_share(tmp_path: Path) -> None:
    key = backdoor_roth_key(household(tmp_path, basis="3000.00"))
    # Line 3: 7,000.00 + 3,000.00 = 10,000.00; line 10: 10,000.00 / 100,000.00 = 0.100; line 11: 700.00.
    # Taxable 7,000.00 - 700.00 = 6,300.00; carried 10,000.00 - 700.00 = 9,300.00.
    assert (key.taxable_amount, key.basis_carried) == (Decimal("6300.00"), Decimal("9300.00"))


def test_an_ira_with_no_year_end_value_is_refused(tmp_path: Path) -> None:
    with pytest.raises(UnsettledBackdoorError, match=B):
        backdoor_roth_key(household(tmp_path, year_end_cash=False))


def test_a_household_with_no_backdoor_roth_is_refused(book: Path) -> None:
    assert backdoor_conversions(book / household_dir("HH-2316")) == ()
    with pytest.raises(UnsettledBackdoorError, match="0 people"):
        backdoor_roth_key(book / household_dir("HH-2316"))


@pytest.mark.parametrize("build", ["book", "real_book"])
def test_the_trap_hh_1204_is_taxed_pro_rata(request: pytest.FixtureRequest, build: str) -> None:
    # Luka (P-1204-2) put 7,000.00 into SYN-12040003 on 2025-02-10 (T-1204-0005) and converted it on 2025-02-13
    # (T-1204-0006). His rollover IRA SYN-12040002 on 2025-12-31: 42,871.51 + 142,362.18 of funds and 2,311.23
    # of cash = 187,544.92; SYN-12040003 is empty. Line 9: 194,544.92; line 10: 7,000.00 / 194,544.92 =
    # 0.03598... = 0.036; line 11: 252.00; taxable 6,748.00; carried 7,000.00 - 252.00 = 6,748.00.
    book: Path = request.getfixturevalue(build)
    key = backdoor_roth_key(book / household_dir("HH-1204"))
    assert (key.finding, key.backdoor.person_id, key.backdoor.conversion_ids) == (
        "pro_rata_tax",
        "P-1204-2",
        ("T-1204-0006",),
    )
    assert key.backdoor.year_end_values == (("SYN-12040002", Decimal("187544.92")), ("SYN-12040003", Decimal("0.00")))
    assert (key.backdoor.form.line_10, key.backdoor.form.line_11) == (Decimal("0.036"), Decimal("252.00"))
    assert (key.taxable_amount, key.basis_carried) == (Decimal("6748.00"), Decimal("6748.00"))


@pytest.mark.parametrize("build", ["book", "real_book"])
def test_the_twin_hh_1587_owes_nothing_on_its_conversion(request: pytest.FixtureRequest, build: str) -> None:
    # Daniel's pre-tax money is in the 401(k) SYN-15870002; his only traditional IRA, SYN-15870003, held 0.00 in
    # cash and no funds on 2025-12-31. Line 9: 7,000.00; line 10: 1.000; nothing taxable, nothing carried.
    book: Path = request.getfixturevalue(build)
    key = backdoor_roth_key(book / household_dir("HH-1587"))
    assert key.backdoor.year_end_values == (("SYN-15870003", Decimal("0.00")),)
    assert (key.finding, key.taxable_amount, key.basis_carried) == ("no_pro_rata_tax", Decimal(0), Decimal("0.00"))
    assert {f.label: f.value for f in key.computed_figures}[
        "P-1587-2 Form 8606 line 17, basis in the amount converted"
    ] == (Decimal("7000.00"))


def test_every_archetype_1_pair_agrees_with_the_planters(full_book: Path) -> None:
    households = json.loads((full_book / SEALED_HOUSEHOLDS).read_text())["households"]
    registry = {e["household_id"]: e for e in json.loads((full_book / REGISTRY).read_text())["entries"]}
    pairs = [h for h in households if h["archetype"] == 1]
    assert len(pairs) == 10
    for h in pairs:
        key = backdoor_roth_key(full_book / household_dir(h["household_id"]))
        if h["role"] == "trap":
            figures = {f["label"]: f["value"] for f in registry[h["household_id"]]["figures"]}
            taxable = Decimal(figures["Taxable amount (Form 8606 line 18)"].strip("$").replace(",", ""))
            assert (key.finding, key.taxable_amount) == ("pro_rata_tax", taxable), h["household_id"]
        else:
            assert (key.finding, key.taxable_amount) == ("no_pro_rata_tax", Decimal(0)), h["household_id"]
