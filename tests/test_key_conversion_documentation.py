"""The conversion documentation key behind T-CMP-03 and T-CMP-04: Form 8606 worked by hand from the custodian's
files, the CRM's records of the returns received and the portfolio system's basis."""

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from casebook.keys.conversion_documentation import conversion_key
from casebook.model.files import REGISTRY, SEALED_HOUSEHOLDS, household_dir

YEAR = 2025


def test_the_trap_is_documented_and_taxed_pro_rata(book: Path) -> None:
    key = conversion_key(book / household_dir("HH-4105"), YEAR)
    assert key.finding == "documented"
    assert (key.converted, key.transaction_ids) == (Decimal("60000.00"), ("T-4105-0028",))
    assert key.form_8606_record == "CA-4105-01"
    # Form 8606, by hand: line 2, the basis the 2024 Form 8606 carries (CA-4105-01), 38,500.00; line 6, SYN-41050002
    # on 31 December 2025, 197,164.92 + 90,181.62 + 100,156.28 + cash 5,208.54 = 392,711.36; line 8, 60,000.00;
    # line 9, 452,711.36; line 10, 38,500 / 452,711.36 = 0.08504, so 0.085; line 11, 60,000 x 0.085 = 5,100.00;
    # line 18, 54,900.00; line 14, 38,500 - 5,100 = 33,400.00.
    assert key.lines is not None
    assert (key.lines.line_6, key.lines.line_9, key.lines.line_10) == (
        Decimal("392711.36"),
        Decimal("452711.36"),
        Decimal("0.085"),
    )
    assert (key.basis_prior, key.nontaxable, key.taxable) == (
        Decimal("38500.00"),
        Decimal("5100.00"),
        Decimal("54900.00"),
    )
    assert key.lines.line_14 == Decimal("33400.00")
    # The Form 1099-R reports all 60,000.00 in box 2a.
    assert key.reported_taxable == Decimal("60000.00")
    assert [i.records for i in key.issues] == [("SYN-41050002-1099R-7-2025", "CA-4105-01")]


def test_the_twin_is_unresolved_for_want_of_a_form_8606(book: Path) -> None:
    key = conversion_key(book / household_dir("HH-4633"), YEAR)
    assert key.finding == "unresolved"
    assert (key.converted, key.taxable, key.basis_prior) == (Decimal("60000.00"), None, None)
    # CA-4633-01: the 2024 return with no Form 8606; CA-4633-02: Beatriz's account of nondeductible contributions.
    assert [i.records for i in key.issues] == [("CA-4633-01", "CA-4633-02")]
    assert {f.label: f.value for f in key.computed_figures}["taxable if no basis"] == Decimal("60000.00")


def test_a_background_trap_worked_by_hand(full_book: Path) -> None:
    key = conversion_key(full_book / household_dir("HH-0364"), YEAR)
    # Line 2 19,440.00 (CA-0364-01); line 6 177,271.60 + 66,692.85 + 84,497.07 + cash 11,285.73 = 339,747.25;
    # line 9 365,647.25; line 10 19,440 / 365,647.25 = 0.05317, so 0.053; line 11 25,900 x 0.053 = 1,372.70;
    # line 18 24,527.30.
    assert key.lines is not None
    assert (key.lines.line_6, key.lines.line_10) == (Decimal("339747.25"), Decimal("0.053"))
    assert (key.nontaxable, key.taxable) == (Decimal("1372.70"), Decimal("24527.30"))


def test_every_conversion_pair_agrees_with_the_planters(full_book: Path) -> None:
    """A cross-check, not the source: each trap's registry entry, and each twin the planter calls unresolved."""
    entries = json.loads((full_book / REGISTRY).read_text())["entries"]
    traps = {e["household_id"]: e for e in entries if e["type"] == "conversion_ira_basis"}
    # Archetype 4's featured pair and its three public background pairs; pair 2 is a private pair.
    assert len(traps) == 4
    for household, entry in traps.items():
        figures = {f["label"]: f["value"] for f in entry["figures"]}
        key = conversion_key(full_book / household_dir(household), YEAR)
        assert key.finding == "documented"
        assert f"${key.taxable:,}" == figures["Taxable amount (Form 8606 line 18)"], household
    sealed = json.loads((full_book / SEALED_HOUSEHOLDS).read_text())["households"]
    twins = [h["household_id"] for h in sealed if h["archetype"] == 4 and h["role"] == "twin"]
    assert len(twins) == 4
    assert all(conversion_key(full_book / household_dir(h), YEAR).finding == "unresolved" for h in twins)


def test_the_key_gives_the_same_answer_on_the_real_ticker_build(book: Path, real_book: Path) -> None:
    for household in ("HH-4105", "HH-4633"):
        assert (
            conversion_key(real_book / household_dir(household), YEAR).to_dict()
            == conversion_key(book / household_dir(household), YEAR).to_dict()
        )


def _without(book: Path, tmp_path: Path, household: str, activity_id: str) -> Path:
    root = tmp_path / household
    shutil.copytree(book / household_dir(household), root)
    path = root / "crm" / "crm.json"
    crm = json.loads(path.read_text())
    crm["activities"] = [a for a in crm["activities"] if a["activity_id"] != activity_id]
    path.write_text(json.dumps(crm))
    return root


def test_with_no_claim_of_basis_the_whole_conversion_is_documented_as_taxable(book: Path, tmp_path: Path) -> None:
    key = conversion_key(_without(book, tmp_path, "HH-4633", "CA-4633-02"), YEAR)
    # The 2024 return reports no basis and nothing claims any: line 2 is 0.00, so line 10 is 0.000.
    assert (key.finding, key.basis_prior, key.taxable) == ("documented", Decimal("0.00"), Decimal("60000.00"))
    assert key.issues == ()


@pytest.mark.parametrize("household", ["HH-4105"])
def test_basis_with_no_form_8606_on_file_is_unresolved(book: Path, tmp_path: Path, household: str) -> None:
    """The portfolio system carries 38,500.00 of basis, but with CA-4105-01 gone nothing documents it."""
    key = conversion_key(_without(book, tmp_path, household, "CA-4105-01"), YEAR)
    assert (key.finding, key.taxable) == ("unresolved", None)
