"""Slice 6: archetype 3's background pairs, an executive's RSU releases, drawn from the seed."""

import csv
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.build import build_book
from casebook.checks import check_book
from casebook.generate.background import background_ids, draw_pair
from casebook.securities.market import build_market
from casebook.securities.master import load_master

from .conftest import SCRIPTS, SEED

ARCHETYPE = 3
SCENARIO = "2026-04-15"
OPENING = "2024-12-31"


@pytest.fixture(scope="module")
def drawn(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("background-a03") / "book"
    empty = tmp_path_factory.mktemp("no-scripts")
    build_book(SEED, out, empty, background=True, background_archetypes=frozenset({ARCHETYPE}))
    return out


@pytest.fixture(scope="module")
def featured(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("featured-a03") / "book"
    build_book(SEED, out, SCRIPTS / f"archetype-{ARCHETYPE}")
    return out


def households(book: Path) -> list[dict[str, Any]]:
    return json.loads((book / "sealed" / "households.json").read_text())["households"]


def rows(book: Path, household_id: str, name: str) -> list[dict[str, str]]:
    with (book / "households" / household_id / "custodian" / name).open() as handle:
        return list(csv.DictReader(handle))


def opening_balances(book: Path, household_id: str) -> dict[str, Decimal]:
    """Each account's 31 December 2024 balance: its positions' market value plus its cash."""
    balances: dict[str, Decimal] = {}
    for cash in rows(book, household_id, "cash.csv"):
        if cash["valuation_date"] == OPENING:
            balances[cash["account_id"]] = Decimal(cash["settled_cash"]) + Decimal(cash["unsettled_cash"])
    for position in rows(book, household_id, "positions.csv"):
        if position["valuation_date"] == OPENING:
            balances[position["account_id"]] += Decimal(position["market_value"])
    return balances


def member_names(book: Path, household_id: str) -> set[str]:
    data = json.loads((book / "households" / household_id / "portfolio" / "household.json").read_text())
    return {m["name"] for m in data["household_membership"]}


def figure(entry: dict[str, Any], label: str) -> str:
    return next(f["value"] for f in entry["figures"] if f["label"] == label)


def test_four_drawn_pairs_build_and_pass_every_check(drawn: Path) -> None:
    sealed = households(drawn)
    assert sorted((h["archetype"], h["pair"], h["role"]) for h in sealed) == sorted(
        (ARCHETYPE, pair, role) for pair in (2, 3, 4, 5) for role in ("trap", "twin")
    )
    assert {h["set"] for h in sealed} == {"background"}
    assert {h["twin_kind"] for h in sealed if h["role"] == "twin"} == {"clean"}
    report = check_book(drawn)
    assert len(report.lines) == 72
    assert report.passed, [(line.household_id, line.check, line.problems) for line in report.lines if not line.passed]


def test_drawing_the_same_pair_twice_gives_the_same_scripts() -> None:
    market = build_market(load_master(), SEED)
    ids = background_ids(SEED)
    index = 2 * ((ARCHETYPE - 1) * 4 + 1)  # pair 3, the second background pair
    first = draw_pair(SEED, ARCHETYPE, 3, ids[index], ids[index + 1], market)
    again = draw_pair(SEED, ARCHETYPE, 3, ids[index], ids[index + 1], market)
    assert first == again
    assert first[0].background and first[1].background
    assert first[0].source == f"background/{ids[index]}"


def test_the_pairs_differ_from_each_other_and_from_the_featured_pair(drawn: Path, featured: Path) -> None:
    drawn_ids = [h["household_id"] for h in households(drawn)]
    featured_ids = [h["household_id"] for h in households(featured)]
    assert sorted(featured_ids) == ["HH-3058", "HH-3462"]
    names = [member_names(drawn, h) for h in drawn_ids]
    assert len(set().union(*names)) == sum(len(n) for n in names)
    assert not set().union(*names) & set().union(*(member_names(featured, h) for h in featured_ids))
    balances = [v for h in drawn_ids for v in opening_balances(drawn, h).values()]
    assert len(set(balances)) == len(balances)
    assert not set(balances) & {v for h in featured_ids for v in opening_balances(featured, h).values()}


def test_the_trap_overstates_the_gain_by_the_release_value_of_the_shares_sold(drawn: Path) -> None:
    """The custodian books each release at no cost, so the gain it shows on the released shares sold
    is too large by their release value: shares times the price on the confirmation."""
    registry = json.loads((drawn / "sealed" / "registry.json").read_text())["entries"]
    traps = [h["household_id"] for h in households(drawn) if h["role"] == "trap"]
    assert len(traps) == 4
    for household_id in traps:
        crm = json.loads((drawn / "households" / household_id / "crm" / "crm.json").read_text())
        releases = sorted(
            (a["refers_to"], Decimal(a["units"]), Decimal(a["price"]))
            for a in crm["activities"]
            if a["kind"] == "rsu_release_confirmation"
        )
        sales = [t for t in rows(drawn, household_id, "transactions.csv") if t["type"] == "SELL"]
        assert len(sales) == 1
        to_sell = Decimal(sales[0]["units"])
        omitted = Decimal(0)
        for _, units, price in releases:  # the earliest releases are sold first
            taken = min(units, to_sell)
            omitted += (taken * price).quantize(Decimal("0.01"))
            to_sell -= taken
        assert to_sell == 0
        entry = next(e for e in registry if e["household_id"] == household_id)
        assert figure(entry, "Gain overstated") == f"${omitted:,.2f}"
        assert figure(entry, "Basis the custodian shows") == "$0.00"
        # And the employer stock is above the IPS limit on the scenario date.
        stock = sales[0]["security_id"]
        held = sum(
            Decimal(p["market_value"])
            for p in rows(drawn, household_id, "positions.csv")
            if p["valuation_date"] == SCENARIO and p["security_id"] == stock
        )
        total = sum(
            Decimal(p["market_value"])
            for p in rows(drawn, household_id, "positions.csv")
            if p["valuation_date"] == SCENARIO
        ) + sum(
            Decimal(c["settled_cash"]) + Decimal(c["unsettled_cash"])
            for c in rows(drawn, household_id, "cash.csv")
            if c["valuation_date"] == SCENARIO
        )
        ips = json.loads((drawn / "households" / household_id / "portfolio" / "ips.json").read_text())
        assert held / total > Decimal(ips["concentration_limit"]["share_of_household"])
