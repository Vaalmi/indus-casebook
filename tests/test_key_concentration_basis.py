"""The concentration and basis key behind T-CMP-01 and T-CMP-02, against the lots worked by hand from the
custodian's tax lots and realized lots and the CRM's release confirmations."""

import csv
import io
import json
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

from casebook.keys.concentration_basis import concentration_basis_key
from casebook.model.files import REGISTRY, TAX_LOTS_COLUMNS, csv_text, household_dir

AS_OF, TAX_YEAR = date(2026, 4, 15), 2025


def test_the_trap_shows_no_basis_on_any_released_share(book: Path) -> None:
    key = concentration_basis_key(book / household_dir("HH-3058"), AS_OF, TAX_YEAR)
    assert key.finding == "issues_found"
    assert key.above_limit == {"SEC-0028": Decimal("1265646.04")}
    # Held on 15 April 2026, each 800 shares at $0.00: L-E-3058-0033 released 20 August 2025 at 236.83
    # (CA-3058-03), 189,464.00; L-E-3058-0047 released 20 November 2025 at 274.64 (CA-3058-04), 219,712.00.
    assert [(lot.lot_id, lot.activity_id, lot.shown, lot.supported) for lot in key.held] == [
        ("L-E-3058-0033", "CA-3058-03", Decimal("0.00"), Decimal("189464.00")),
        ("L-E-3058-0047", "CA-3058-04", Decimal("0.00"), Decimal("219712.00")),
    ]
    assert key.basis_understated == Decimal("409176.00")
    # Sold on 12 December 2025 (T-3058-0048), each 800 at $0.00: L-E-3058-0005 at 216.06, 172,848.00;
    # L-E-3058-0019 at 229.90, 183,920.00. The gain shown, 437,776.00, is 356,768.00 too much.
    assert [(lot.lot_id, lot.transaction_id, lot.supported) for lot in key.sold] == [
        ("L-E-3058-0005", "T-3058-0048", Decimal("172848.00")),
        ("L-E-3058-0019", "T-3058-0048", Decimal("183920.00")),
    ]
    assert key.gain_overstated == Decimal("356768.00")
    assert not key.basis_reliable
    shown = {f.label: f.value for f in key.computed_figures}
    # Proceeds 437,776.00 less the true basis: 81,008.00.
    assert shown["2025 true gain on released shares sold"] == Decimal("81008.00")
    assert [i.records for i in key.issues] == [
        ("SEC-0028",),
        ("L-E-3058-0033", "L-E-3058-0047"),
        ("L-E-3058-0005", "L-E-3058-0019"),
    ]


def test_the_trap_agrees_with_the_planters_registry_figures(book: Path) -> None:
    """A cross-check, not the source: PI-0004's figures, written by the planter."""
    entry = next(e for e in json.loads((book / REGISTRY).read_text())["entries"] if e["item_id"] == "PI-0004")
    figures = {f["label"]: f["value"] for f in entry["figures"]}
    key = concentration_basis_key(book / household_dir("HH-3058"), AS_OF, TAX_YEAR)
    assert figures["True basis"] == "$356,768.00" == f"${key.gain_overstated:,}"
    assert figures["Basis missing on released shares still held"] == f"${key.basis_understated:,}"


def test_the_twin_carries_each_release_at_its_value(book: Path) -> None:
    key = concentration_basis_key(book / household_dir("HH-3462"), AS_OF, TAX_YEAR)
    assert key.finding == "no_issues"
    assert key.above_limit == {}
    # 200 left of the August release at 393.07 = 78,614.00; 400 of November's at 410.22 = 164,088.00.
    assert [(lot.lot_id, lot.shown, lot.supported) for lot in key.held] == [
        ("L-E-3462-0033", Decimal("78614.00"), Decimal("78614.00")),
        ("L-E-3462-0047", Decimal("164088.00"), Decimal("164088.00")),
    ]
    # Sold on 12 December 2025: 400 at 392.54 = 157,016.00, 400 at 408.82 = 163,528.00, 200 at 393.07 = 78,614.00.
    assert [lot.supported for lot in key.sold] == [Decimal("157016.00"), Decimal("163528.00"), Decimal("78614.00")]
    assert key.basis_reliable
    assert (key.basis_understated, key.gain_overstated) == (Decimal(0), Decimal(0))
    assert key.issues == ()


def test_the_key_gives_the_same_answer_on_the_real_ticker_build(book: Path, real_book: Path) -> None:
    for household in ("HH-3058", "HH-3462"):
        default = concentration_basis_key(book / household_dir(household), AS_OF, TAX_YEAR).to_dict()
        real = concentration_basis_key(real_book / household_dir(household), AS_OF, TAX_YEAR).to_dict()
        assert real == default


def test_lots_corrected_at_the_custodian_leave_only_the_concentration(book: Path, tmp_path: Path) -> None:
    root = tmp_path / "HH-3058"
    shutil.copytree(book / household_dir("HH-3058"), root)
    path = root / "custodian" / "tax_lots.csv"
    rows = list(csv.DictReader(io.StringIO(path.read_text())))
    for row in rows:
        if row["lot_id"] == "L-E-3058-0033":
            row["cost_basis"] = "189464.00"
        if row["lot_id"] == "L-E-3058-0047":
            row["cost_basis"] = "219712.00"
    path.write_text(csv_text(TAX_LOTS_COLUMNS, rows))
    key = concentration_basis_key(root, AS_OF, TAX_YEAR)
    assert key.basis_understated == Decimal(0)
    # The realized lots still carry no basis, so the review still finds the sale's gain overstated.
    assert key.gain_overstated == Decimal("356768.00")
    assert [i.records for i in key.issues] == [("SEC-0028",), ("L-E-3058-0005", "L-E-3058-0019")]
