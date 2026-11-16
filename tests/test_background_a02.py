"""Archetype 2's background pairs: a December sale over the NIIT threshold, drawn from the seed, built and checked."""

import csv
import json
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.build import build_book
from casebook.checks import check_book
from casebook.generate.background import draw_pair
from casebook.generate.script import HouseholdScript, load_scripts
from casebook.securities.market import build_market
from casebook.securities.master import load_master

from .conftest import SCRIPTS, SEED

D = Decimal
ARCHETYPE = 2


def rows(path: Path) -> list[dict[str, str]]:
    with path.open() as handle:
        return list(csv.DictReader(handle))


def sealed(book: Path) -> list[dict[str, Any]]:
    return json.loads((book / "sealed" / "households.json").read_text())["households"]


def opening_values(script: HouseholdScript) -> set[Decimal]:
    return {h.value for a in script.accounts for h in a.holdings} | {a.cash for a in script.accounts if a.cash}


def names(script: HouseholdScript) -> set[str]:
    return {p.name for p in script.household.members}


@pytest.fixture(scope="module")
def drawn(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("background-a02") / "book"
    empty = tmp_path_factory.mktemp("no-scripts")
    build_book(SEED, out, empty, background=True, background_archetypes=frozenset({ARCHETYPE}))
    return out


@pytest.fixture(scope="module")
def pairs(drawn: Path) -> dict[int, tuple[HouseholdScript, HouseholdScript]]:
    market = build_market(load_master(), SEED)
    ids = {(h["pair"], h["role"]): h["household_id"] for h in sealed(drawn)}
    return {
        pair: draw_pair(SEED, ARCHETYPE, pair, ids[pair, "trap"], ids[pair, "twin"], market) for pair in (2, 3, 4, 5)
    }


def test_the_eight_households_build_and_pass_every_check(drawn: Path) -> None:
    households = sealed(drawn)
    assert sorted((h["archetype"], h["pair"], h["role"]) for h in households) == sorted(
        (ARCHETYPE, pair, role) for pair in (2, 3, 4, 5) for role in ("trap", "twin")
    )
    assert {h["set"] for h in households} == {"background"}
    assert {h["twin_kind"] for h in households if h["role"] == "twin"} == {"near_miss"}
    report = check_book(drawn)
    assert len(report.lines) == 72
    assert report.passed, report.render()


def test_the_same_pair_drawn_twice_is_the_same(drawn: Path) -> None:
    market = build_market(load_master(), SEED)
    ids = {(h["pair"], h["role"]): h["household_id"] for h in sealed(drawn)}
    first = draw_pair(SEED, ARCHETYPE, 3, ids[3, "trap"], ids[3, "twin"], market)
    again = draw_pair(SEED, ARCHETYPE, 3, ids[3, "trap"], ids[3, "twin"], market)
    assert first == again


def test_the_pairs_differ_from_each_other_and_from_the_featured_pair(
    pairs: dict[int, tuple[HouseholdScript, HouseholdScript]],
) -> None:
    drawn = [script for pair in pairs.values() for script in pair]
    featured = load_scripts(SCRIPTS / f"archetype-{ARCHETYPE}")
    assert len(featured) == 2
    for i, one in enumerate(drawn):
        for other in drawn[i + 1 :]:
            assert not names(one) & names(other)
            assert opening_values(one) != opening_values(other)
        for known in featured:
            assert not names(one) & names(known)
            assert not opening_values(one) & opening_values(known)


def test_each_household_s_modified_agi_follows_from_the_files(drawn: Path) -> None:
    entries = {e["household_id"]: e for e in json.loads((drawn / "sealed" / "registry.json").read_text())["entries"]}
    # IRC section 1411(b): $250,000 for a joint return, $200,000 for a single filer; the tax is 3.8%.
    thresholds = {"married_filing_jointly": D(250000), "single": D(200000)}
    for household in sealed(drawn):
        hh_id = household["household_id"]
        root = drawn / "households" / hh_id
        taxable = {
            a["account_id"]
            for a in rows(root / "custodian" / "accounts.csv")
            if a["account_type"] in ("joint_taxable", "individual_taxable")
        }
        dividends = sum(
            (
                D(t["amount"])
                for t in rows(root / "custodian" / "transactions.csv")
                if t["type"] == "DIVIDEND" and t["account_id"] in taxable and t["trade_date"].startswith("2025-")
            ),
            D(0),
        )
        sales = [
            r
            for r in rows(root / "custodian" / "realized_lots.csv")
            if r["account_id"] in taxable and r["sold_date"].startswith("2025-12")
        ]
        gain = sum((D(r["proceeds"]) - D(r["cost_basis"]) for r in sales), D(0))
        crm = json.loads((root / "crm" / "crm.json").read_text())["activities"]
        w2 = next(a["summary"] for a in crm if a["kind"] == "document_received")
        wages = sum((D(w.replace(",", "")) for w in re.findall(r"wages \$([\d,]+\.\d\d)", w2)), D(0))
        (unit,) = json.loads((root / "portfolio" / "household.json").read_text())["tax_units"]
        threshold = thresholds[unit["filing_status"]]
        magi = wages + dividends + gain
        assert gain > 0
        if household["role"] == "twin":
            # A near miss: under the threshold by no more than $25,000.
            assert threshold - D(25000) <= magi < threshold
            continue
        assert magi > threshold >= magi - gain
        tax = (D("0.038") * min(dividends + gain, magi - threshold)).quantize(D("0.01"), rounding=ROUND_HALF_UP)
        figures = {f["label"]: f["value"] for f in entries[hh_id]["figures"]}
        assert figures["Modified AGI"] == f"${magi:,.2f}"
        assert figures["Net investment income tax"] == f"${tax:,.2f}"
