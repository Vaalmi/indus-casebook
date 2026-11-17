"""The IPS review key: a household's single-stock concentration and drift on a day, worked by hand from its
custodian files and IPS, and the book-level sweep behind T-CMP-05."""

import json
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from casebook.keys.ips_review import UnsettledIpsError, ips_review, ips_sweep_key, single_stocks
from casebook.model.files import REGISTRY, household_dir

from .conftest import PUBLIC_HOUSEHOLDS

AS_OF = date(2026, 4, 15)


def test_the_trap_holds_its_employer_stock_above_the_limit_and_drifts_in_every_class(book: Path) -> None:
    review = ips_review(book / household_dir("HH-3058"), AS_OF)
    # Positions on 15 April 2026 by account: 1,671,974.38 + 459,546.00 + 966,236.99 + 301,398.52 = 3,399,155.89;
    # cash 39,925.53 + 439,841.31 + 10,702.13 + 5,900.01 = 496,368.98; together 3,895,524.87.
    assert review.total == Decimal("3895524.87")
    # Bramwell Devices Group: 825,134.04 joint + 440,512.00 stock plan = 1,265,646.04, 32.49% against 15%.
    # The large cap index fund, 737,131.47 (18.92%), is a fund, so not a concentration.
    [stock] = review.concentrations
    assert (stock.security_id, stock.value, stock.limit) == ("SEC-0028", Decimal("1265646.04"), Decimal("0.15"))
    # US equity 436,021.52 + 737,131.47 + 214,603.48 + 1,265,646.04 = 2,653,402.51, 68.11% against 60 +/- 5;
    # international 159,950.70, 4.11% against 10 +/- 4; fixed income 356,697.16 + 229,105.52 = 585,802.68,
    # 15.04% against 28 +/- 5.
    assert [(d.asset_class, d.value) for d in review.drifts] == [
        ("US equity", Decimal("2653402.51")),
        ("International equity", Decimal("159950.70")),
        ("Fixed income", Decimal("585802.68")),
    ]
    assert review.evidence == ("SEC-0028", "US equity", "International equity", "Fixed income")
    shown = {f.label: f.value for f in review.computed_figures}
    assert shown["SEC-0028 share, percent"] == Decimal("32.49")
    assert shown["concentration limit, percent"] == Decimal("15.00")


def test_the_twin_holds_its_employer_stock_within_the_limit(book: Path) -> None:
    review = ips_review(book / household_dir("HH-3462"), AS_OF)
    # Positions 3,299,418.62 and cash 477,771.30: 3,777,189.92. Ellisar Search Holdings, 600 x 417.82 =
    # 250,692.00, is 6.64%; the index fund at 40.52% is a fund.
    assert review.total == Decimal("3777189.92")
    assert review.concentrations == ()
    assert {f.label: f.value for f in review.computed_figures}["SEC-0030 share, percent"] == Decimal("6.64")
    # Fixed income 318,629.16 + 23,982.84 + 76,897.36 + 250,933.08 = 670,442.44, 17.75% against 30 +/- 5.
    assert [(d.asset_class, d.value) for d in review.drifts] == [("Fixed income", Decimal("670442.44"))]


def test_a_fund_is_never_a_single_stock_and_the_rule_reads_ids_not_names() -> None:
    stocks = single_stocks()
    # Larkspur Total Market Fund, Fernhollow Large Cap Index Fund: funds; Bramwell Devices Group, Ellisar
    # Search Holdings, Orrin Software Group: single companies.
    assert not {"SEC-0001", "SEC-0013"} & stocks
    assert {"SEC-0028", "SEC-0030", "SEC-0004"} <= stocks


# Every household above a single-stock limit or outside a band on 15 April 2026, with what it must be named with.
SWEEP = {
    "HH-0221": ("SEC-0040",),
    "HH-0376": ("SEC-0032",),
    "HH-0816": ("SEC-0005",),
    "HH-0984": ("SEC-0048",),
    "HH-3058": ("SEC-0028", "US equity", "International equity", "Fixed income"),
    "HH-3462": ("Fixed income",),
    "HH-5271": ("US equity", "Fixed income"),
    "HH-5814": ("US equity", "Fixed income"),
    "HH-6047": ("US equity", "Fixed income"),
    "HH-6590": ("US equity", "Fixed income"),
    "HH-9234": ("US equity", "Fixed income"),
    "HH-9571": ("US equity", "Fixed income"),
}


def test_the_sweep_finds_twelve_households_on_the_public_book(full_book: Path) -> None:
    key = ips_sweep_key(full_book, AS_OF)
    assert len(key.checked) == PUBLIC_HOUSEHOLDS
    assert dict(key.found) == SWEEP
    assert key.unresolved == ()


def test_the_planted_concentrations_are_the_five_registered_ones(full_book: Path) -> None:
    """The registry records the five executives' stock as crossing the limit by design; the drifts are the
    featured households' own, which no planter registers, and the files show them all the same."""
    entries = json.loads((full_book / REGISTRY).read_text())["entries"]
    registered = {e["household_id"] for e in entries if "concentration" in e["crosses"]}
    concentrated = {h for h, ids in SWEEP.items() if any(i.startswith("SEC-") for i in ids)}
    assert concentrated == registered


def test_the_sweep_gives_the_same_answer_on_the_real_ticker_build(real_book: Path, book: Path) -> None:
    assert dict(ips_sweep_key(real_book, AS_OF).found) == dict(ips_sweep_key(book, AS_OF).found)


def test_a_household_whose_crm_records_an_exception_is_refused(book: Path, tmp_path: Path) -> None:
    root = tmp_path / "HH-3058"
    shutil.copytree(book / household_dir("HH-3058"), root)
    crm = json.loads((root / "crm" / "crm.json").read_text())
    crm["agreements"].append({**crm["agreements"][0], "agreement_id": "AGR-3058-9", "kind": "ips_exception"})
    (root / "crm" / "crm.json").write_text(json.dumps(crm))
    with pytest.raises(UnsettledIpsError, match="AGR-3058-9"):
        ips_review(root, AS_OF)
