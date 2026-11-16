"""Archetype 1's background pairs: a backdoor Roth taxed pro rata, drawn from the seed, built and checked."""

import csv
import json
from decimal import Decimal
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
ARCHETYPE = 1
YEAR_END = "2025-12-31"


def rows(path: Path) -> list[dict[str, str]]:
    with path.open() as handle:
        return list(csv.DictReader(handle))


def sealed(book: Path) -> list[dict[str, Any]]:
    return json.loads((book / "sealed" / "households.json").read_text())["households"]


def year_end_value(root: Path, accounts: set[str]) -> Decimal:
    positions = sum(
        (
            D(p["market_value"])
            for p in rows(root / "custodian" / "positions.csv")
            if p["valuation_date"] == YEAR_END and p["account_id"] in accounts
        ),
        D(0),
    )
    cash = sum(
        (
            D(c["settled_cash"]) + D(c["unsettled_cash"])
            for c in rows(root / "custodian" / "cash.csv")
            if c["valuation_date"] == YEAR_END and c["account_id"] in accounts
        ),
        D(0),
    )
    return positions + cash


def opening_values(script: HouseholdScript) -> set[Decimal]:
    return {h.value for a in script.accounts for h in a.holdings} | {a.cash for a in script.accounts if a.cash}


def names(script: HouseholdScript) -> set[str]:
    return {p.name for p in script.household.members}


@pytest.fixture(scope="module")
def drawn(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("background-a01") / "book"
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


# Each seed-2026 trap's line 6 (its traditional IRAs on 31 December 2025) and taxable amount.
HAND_WORKED = {
    "HH-0218": ("221659.62", "$6,783.00"),
    "HH-0347": ("231265.99", "$6,797.00"),
    "HH-0690": ("187878.56", "$7,672.00"),
    "HH-0844": ("152329.55", "$6,692.00"),
}


def test_each_trap_s_taxable_conversion_follows_from_the_files(drawn: Path) -> None:
    entries = {e["household_id"]: e for e in json.loads((drawn / "sealed" / "registry.json").read_text())["entries"]}
    for household in sealed(drawn):
        root = drawn / "households" / household["household_id"]
        accounts = rows(root / "custodian" / "accounts.csv")
        iras = {a["account_id"] for a in accounts if a["account_type"] == "traditional_ira"}
        plans = {a["account_id"] for a in accounts if a["account_type"] == "401k"}
        transactions = rows(root / "custodian" / "transactions.csv")
        contributed = sum(
            (D(t["amount"]) for t in transactions if t["type"] == "CONTRIBUTION" and t["account_id"] in iras), D(0)
        )
        converted = -sum(
            (D(t["amount"]) for t in transactions if t["type"] == "CONVERSION_OUT" and t["account_id"] in iras), D(0)
        )
        # The 2025 IRA limit, $7,000, plus the $1,000 catch-up at 50 or over; the whole of it converted.
        assert contributed == converted
        assert contributed in (D(7000), D(8000))
        line6 = year_end_value(root, iras)
        if household["role"] == "twin":
            # Form 8606 line 6 counts IRAs only: the 401(k) holds the pre-tax money, the IRA nothing.
            assert line6 == 0
            assert year_end_value(root, plans) > converted
            continue
        assert not plans and line6 > 0
        # Worked by hand for seed 2026 (reviewer B, slice 6 round 1: no figure recomputed the way the
        # planter does). Line 10 = contribution / (line 6 + converted), to three places:
        # HH-0218 7,000 / 228,659.62 = 0.0306 -> 0.031, nontaxable 217.00, taxable 6,783.00;
        # HH-0347 7,000 / 238,265.99 = 0.0294 -> 0.029, 203.00, 6,797.00;
        # HH-0690 8,000 / 195,878.56 = 0.0408 -> 0.041, 328.00, 7,672.00;
        # HH-0844 7,000 / 159,329.55 = 0.0439 -> 0.044, 308.00, 6,692.00.
        expected = HAND_WORKED[household["household_id"]]
        assert line6 == D(expected[0])
        figures = {f["label"]: f["value"] for f in entries[household["household_id"]]["figures"]}
        assert figures["Taxable amount (Form 8606 line 18)"] == expected[1]
