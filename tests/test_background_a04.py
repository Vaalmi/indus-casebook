"""Archetype 4's background pairs: a Roth conversion from an IRA with basis, drawn from the seed, built and checked."""

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
ARCHETYPE = 4
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
    out = tmp_path_factory.mktemp("background-a04") / "book"
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
    assert {h["twin_kind"] for h in households if h["role"] == "twin"} == {"unresolved"}
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


# Each seed-2026 trap's line 6 (its traditional IRAs on 31 December 2025) and its Form 8606 figures.
HAND_WORKED = {
    "HH-0364": ("339747.25", "$1,372.70", "$24,527.30", "$18,067.30"),
    "HH-0562": ("335688.27", "$2,946.30", "$45,353.70", "$20,563.70"),
    "HH-0687": ("297758.12", "$6,022.40", "$88,077.60", "$18,877.60"),
    "HH-0985": ("480325.36", "$1,108.80", "$24,091.20", "$20,911.20"),
}


def test_each_trap_s_taxable_conversion_follows_from_the_files(drawn: Path) -> None:
    entries = {e["household_id"]: e for e in json.loads((drawn / "sealed" / "registry.json").read_text())["entries"]}
    for household in sealed(drawn):
        hh_id = household["household_id"]
        root = drawn / "households" / hh_id
        iras = {
            a["account_id"] for a in rows(root / "custodian" / "accounts.csv") if a["account_type"] == "traditional_ira"
        }
        transactions = rows(root / "custodian" / "transactions.csv")
        assert not [t for t in transactions if t["type"] == "CONTRIBUTION" and t["account_id"] in iras]
        (converted,) = [
            -D(t["amount"]) for t in transactions if t["type"] == "CONVERSION_OUT" and t["account_id"] in iras
        ]
        profile = json.loads((root / "portfolio" / "tax_profile.json").read_text())
        basis = sum((D(b["basis"]) for b in profile["ira_basis"]), D(0))
        if household["role"] == "twin":
            # Unresolved: no basis on file, and a CRM record of a belief in it.
            crm = json.loads((root / "crm" / "crm.json").read_text())["activities"]
            assert basis == 0
            assert any("nondeductible" in a["summary"] and "Form 8606" in a["summary"] for a in crm)
            continue
        # Worked by hand for seed 2026 (reviewer B, slice 6 round 1). Line 10 = basis / (line 6 +
        # converted), to three places; nontaxable = converted x line 10; carried = basis - nontaxable:
        # HH-0364 19,440 / 365,647.25 = 0.0532 -> 0.053: 1,372.70, taxable 24,527.30, carried 18,067.30;
        # HH-0562 23,510 / 383,988.27 = 0.0612 -> 0.061: 2,946.30, 45,353.70, 20,563.70;
        # HH-0687 24,900 / 391,858.12 = 0.0635 -> 0.064: 6,022.40, 88,077.60, 18,877.60;
        # HH-0985 22,020 / 505,525.36 = 0.0436 -> 0.044: 1,108.80, 24,091.20, 20,911.20.
        line6, nontaxable, taxable, carried = HAND_WORKED[hh_id]
        assert year_end_value(root, iras) == D(line6)
        figures = {f["label"]: f["value"] for f in entries[hh_id]["figures"]}
        assert figures["Converted"] == f"${converted:,.2f}"
        assert figures["Nontaxable part (Form 8606 line 17)"] == nontaxable
        assert figures["Taxable amount (Form 8606 line 18)"] == taxable
        assert figures["Basis carried to 2026 (Form 8606 line 14)"] == carried
