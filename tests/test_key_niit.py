"""The NIIT key: the featured pair of archetype 2 worked by hand on both builds, a copy of the twin pushed over
the threshold, the refusals, and every archetype 2 pair in the whole book against the planters' figures."""

import csv
import io
import json
import re
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from casebook.keys.niit import UnsettledNiitError, niit_key
from casebook.model.files import (
    DOCUMENTS_INDEX,
    REALIZED_CSV,
    REGISTRY,
    SEALED_HOUSEHOLDS,
    TRANSACTIONS_CSV,
    household_dir,
    json_text,
)


def _copy(book: Path, household: str, tmp_path: Path) -> Path:
    root = tmp_path / household
    shutil.copytree(book / household_dir(household), root)
    return root


@pytest.mark.parametrize("build", ["book", "real_book"])
def test_the_trap_hh_2316_owes_the_tax(request: pytest.FixtureRequest, build: str) -> None:
    # Forms W-2, box 1: Ingrid 141,500.00 + Kwame 87,000.00 = 228,500.00. The 1099's box 1a for SYN-23160001:
    # 13,483.67 of dividends. T-2316-0035 sold 400 units of SEC-0019 bought in 2009: 103,292.00 - 28,353.28 =
    # 74,938.72. Net investment income 13,483.67 + 74,938.72 = 88,422.39; modified AGI 228,500.00 + 88,422.39 =
    # 316,922.39; over the 250,000.00 joint threshold by 66,922.39, less than the 88,422.39 of income, so the tax
    # is 0.038 x 66,922.39 = 2,543.05082 = 2,543.05. Modified AGI is under 500,000.00: SALT limit 40,000.00.
    # The joint account holds the bond fund SEC-0018 at year end, the IRAs none; the 1099 shows 6,706.86 from it.
    book: Path = request.getfixturevalue(build)
    key = niit_key(book / household_dir("HH-2316"))
    assert key.wages == (("P-2316-1", Decimal("141500.00")), ("P-2316-2", Decimal("87000.00")))
    assert (key.dividends, key.gain) == (Decimal("13483.67"), Decimal("74938.72"))
    assert (key.net_investment_income, key.modified_agi, key.excess) == (
        Decimal("88422.39"),
        Decimal("316922.39"),
        Decimal("66922.39"),
    )
    assert (key.finding, key.niit, key.salt_limit) == ("niit_owed", Decimal("2543.05"), Decimal("40000.00"))
    assert (key.bonds_in_taxable, key.bond_dividends, key.asset_location_point) == (
        ("SEC-0018",),
        Decimal("6706.86"),
        True,
    )
    # Without the December sale, modified AGI would have been 316,922.39 - 74,938.72 = 241,983.67.
    assert {f.label: f.value for f in key.computed_figures}["modified AGI without T-2316-0035"] == Decimal("241983.67")


@pytest.mark.parametrize("build", ["book", "real_book"])
def test_the_twin_hh_2749_stays_under_the_threshold(request: pytest.FixtureRequest, build: str) -> None:
    # W-2s: 131,000.00 + 83,500.00 = 214,500.00. Box 1a: 13,407.79. T-2749-0035's gain: 10,702.89. Net
    # investment income 24,110.68; modified AGI 238,610.68, under 250,000.00 by 11,389.32: no tax.
    book: Path = request.getfixturevalue(build)
    key = niit_key(book / household_dir("HH-2749"))
    assert (key.total_wages, key.dividends, key.gain) == (
        Decimal("214500.00"),
        Decimal("13407.79"),
        Decimal("10702.89"),
    )
    assert (key.modified_agi, key.finding, key.niit) == (Decimal("238610.68"), "no_niit", Decimal("0.00"))
    assert {f.label: f.value for f in key.computed_figures}["modified AGI under the threshold"] == Decimal("11389.32")
    assert (key.bonds_in_taxable, key.bond_dividends) == (("SEC-0018",), Decimal("6449.56"))


def test_another_gain_on_the_twin_brings_the_tax(book: Path, tmp_path: Path) -> None:
    root = _copy(book, "HH-2749", tmp_path)
    realized = (root / REALIZED_CSV).read_text()
    rows = list(csv.DictReader(io.StringIO(realized)))
    extra = {**rows[0], "transaction_id": "T-2749-9999", "gain": "20000.00", "sold_date": "2025-12-15"}
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows([*rows, extra])
    (root / REALIZED_CSV).write_text(out.getvalue())
    key = niit_key(root)
    # 238,610.68 + 20,000.00 = 258,610.68, over by 8,610.68; 0.038 x 8,610.68 = 327.20584 = 327.21.
    assert (key.modified_agi, key.excess, key.niit, key.finding) == (
        Decimal("258610.68"),
        Decimal("8610.68"),
        Decimal("327.21"),
        "niit_owed",
    )


def test_a_form_1099_r_is_income_the_key_refuses_to_guess_at(book: Path, tmp_path: Path) -> None:
    root = _copy(book, "HH-2316", tmp_path)
    index = json.loads((root / DOCUMENTS_INDEX).read_text())
    index["documents"].append(
        {"document_id": "D-R", "file": "r.pdf", "kind": "form_1099_r", "valuation_date": "2025-12-31"}
    )
    (root / DOCUMENTS_INDEX).write_text(json_text(index))
    with pytest.raises(UnsettledNiitError, match="income beyond wages"):
        niit_key(root)


def test_a_retirement_account_flow_is_refused(book: Path, tmp_path: Path) -> None:
    root = _copy(book, "HH-2316", tmp_path)
    text = (root / TRANSACTIONS_CSV).read_text()
    day = "2025-06-02"
    text += f"T-2316-9999,SYN-23160002,{day},{day},DISTRIBUTION,,,,,,,-5000.00,Distribution,{day},{day}\n"
    (root / TRANSACTIONS_CSV).write_text(text)
    with pytest.raises(UnsettledNiitError, match="T-2316-9999"):
        niit_key(root)


def _usd(text: str) -> Decimal:
    return Decimal(text.strip("$").replace(",", ""))


def test_every_archetype_2_pair_agrees_with_the_planters(full_book: Path) -> None:
    households = json.loads((full_book / SEALED_HOUSEHOLDS).read_text())["households"]
    registry = {e["household_id"]: e for e in json.loads((full_book / REGISTRY).read_text())["entries"]}
    pairs = [h for h in households if h["archetype"] == 2]
    assert len(pairs) == 10
    for h in pairs:
        key = niit_key(full_book / household_dir(h["household_id"]))
        if h["role"] == "trap":
            figures = {f["label"]: _usd(f["value"]) for f in registry[h["household_id"]]["figures"]}
            assert (key.finding, key.modified_agi, key.niit) == (
                "niit_owed",
                figures["Modified AGI"],
                figures["Net investment income tax"],
            ), h["household_id"]
        else:
            assert key.finding == "no_niit", h["household_id"]
            # The background twins' explanations state modified AGI; the featured twin's does not.
            stated = re.search(r"modified AGI (\$[\d,]+\.\d{2})", h["explanation"])
            if stated:
                assert key.modified_agi == _usd(stated.group(1)), h["household_id"]
