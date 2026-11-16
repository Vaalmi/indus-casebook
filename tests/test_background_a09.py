"""Slice 6: archetype 9's background pairs, a loss harvested and bought back in an IRA, drawn from the seed."""

import csv
import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.build import build_book
from casebook.checks import check_book
from casebook.generate.background import background_ids, draw_pair
from casebook.securities.market import build_market
from casebook.securities.master import load_master

from .conftest import SCRIPTS, SEED

ARCHETYPE = 9
OPENING = "2024-12-31"
# IRC § 1091(a): 30 days before or after the sale.
WASH_SALE_DAYS = 30


@pytest.fixture(scope="module")
def drawn(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("background-a09") / "book"
    empty = tmp_path_factory.mktemp("no-scripts")
    build_book(SEED, out, empty, background=True, background_archetypes=frozenset({ARCHETYPE}))
    return out


@pytest.fixture(scope="module")
def featured(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("featured-a09") / "book"
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
    assert {h["twin_kind"] for h in sealed if h["role"] == "twin"} == {"near_miss"}
    report = check_book(drawn)
    assert len(report.lines) == 72
    assert report.passed, [(line.household_id, line.check, line.problems) for line in report.lines if not line.passed]


def test_drawing_the_same_pair_twice_gives_the_same_scripts() -> None:
    market = build_market(load_master(), SEED)
    ids = background_ids(SEED)
    index = 2 * ((ARCHETYPE - 1) * 4 + 3)  # pair 5, the last background pair
    first = draw_pair(SEED, ARCHETYPE, 5, ids[index], ids[index + 1], market)
    again = draw_pair(SEED, ARCHETYPE, 5, ids[index], ids[index + 1], market)
    assert first == again
    assert first[0].background and first[1].background
    assert first[1].source == f"background/{ids[index + 1]}"


def test_the_pairs_differ_from_each_other_and_from_the_featured_pair(drawn: Path, featured: Path) -> None:
    drawn_ids = [h["household_id"] for h in households(drawn)]
    featured_ids = [h["household_id"] for h in households(featured)]
    assert sorted(featured_ids) == ["HH-9234", "HH-9571"]
    names = [member_names(drawn, h) for h in drawn_ids]
    assert len(set().union(*names)) == sum(len(n) for n in names)
    assert not set().union(*names) & set().union(*(member_names(featured, h) for h in featured_ids))
    balances = [v for h in drawn_ids for v in opening_balances(drawn, h).values()]
    assert len(set(balances)) == len(balances)
    assert not set(balances) & {v for h in featured_ids for v in opening_balances(featured, h).values()}


def _harvest(book: Path, household_id: str) -> tuple[Decimal, Decimal, date, list[tuple[date, Decimal]]]:
    """The loss sale's loss and units, its day, and the IRA purchases of the same fund (day, units)."""
    realized = rows(book, household_id, "realized_lots.csv")
    assert len({r["transaction_id"] for r in realized}) == 1
    loss = sum((Decimal(r["gain"]) for r in realized), Decimal(0))
    sold = sum((Decimal(r["units"]) for r in realized), Decimal(0))
    sold_on = date.fromisoformat(realized[0]["sold_date"])
    fund, seller = realized[0]["security_id"], realized[0]["account_id"]
    accounts = {a["account_id"]: a["account_type"] for a in rows(book, household_id, "accounts.csv")}
    bought = [
        (date.fromisoformat(t["trade_date"]), Decimal(t["units"]))
        for t in rows(book, household_id, "transactions.csv")
        if t["type"] == "BUY"
        and t["security_id"] == fund
        and t["account_id"] != seller
        and accounts[t["account_id"]] in ("traditional_ira", "roth_ira")
    ]
    return loss, sold, sold_on, bought


def test_the_trap_disallows_the_loss_on_the_units_replaced_and_the_twin_buys_outside_the_window(
    drawn: Path,
) -> None:
    registry = json.loads((drawn / "sealed" / "registry.json").read_text())["entries"]
    for household in households(drawn):
        loss, sold, sold_on, bought = _harvest(drawn, household["household_id"])
        assert loss < 0 and bought
        gaps = [abs((day - sold_on).days) for day, _ in bought]
        if household["role"] == "twin":
            assert min(gaps) > WASH_SALE_DAYS
            continue
        replaced = min(
            sum((u for (_, u), g in zip(bought, gaps, strict=True) if g <= WASH_SALE_DAYS), Decimal(0)), sold
        )
        assert replaced > 0
        disallowed = (-loss * replaced / sold).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        entry = next(e for e in registry if e["household_id"] == household["household_id"])
        assert figure(entry, "Disallowed loss") == f"${disallowed:,.2f}"
        assert figure(entry, "Allowed loss") == f"${-loss - disallowed:,.2f}"
