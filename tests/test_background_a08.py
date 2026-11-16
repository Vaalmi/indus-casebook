"""Slice 6: archetype 8's background pairs, a spouse's death and the step-up, drawn from the seed.

Archetype 8's featured pair is held out until the freeze, so the drawn pairs are compared with each
other here; that they differ from the featured pair is checked where the held-out set is built.
"""

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

from .conftest import SEED

ARCHETYPE = 8
OPENING = "2024-12-31"
SCENARIO = "2026-04-15"
CENT = Decimal("0.01")
# IRC § 2040(b): half of a spouses' qualified joint interest steps up at the first death.
HALF = Decimal("0.5")
# IRS Publication 590-B (2025), Table III, for owners aged 73 to 79 at the end of 2025.
UNIFORM_LIFETIME = {73: "26.5", 74: "25.5", 75: "24.6", 76: "23.7", 77: "22.9", 78: "22.0", 79: "21.1"}


@pytest.fixture(scope="module")
def drawn(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("background-a08") / "book"
    empty = tmp_path_factory.mktemp("no-scripts")
    build_book(SEED, out, empty, background=True, background_archetypes=frozenset({ARCHETYPE}))
    return out


def households(book: Path) -> list[dict[str, Any]]:
    return json.loads((book / "sealed" / "households.json").read_text())["households"]


def rows(book: Path, household_id: str, name: str) -> list[dict[str, str]]:
    with (book / "households" / household_id / "custodian" / name).open() as handle:
        return list(csv.DictReader(handle))


def portfolio(book: Path, household_id: str) -> dict[str, Any]:
    return json.loads((book / "households" / household_id / "portfolio" / "household.json").read_text())


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


def figure(entry: dict[str, Any], label: str) -> str:
    return next(f["value"] for f in entry["figures"] if f["label"] == label)


def usd(value: Decimal) -> str:
    return f"${value:,.2f}"


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
    index = 2 * ((ARCHETYPE - 1) * 4 + 0)  # pair 2, the first background pair
    first = draw_pair(SEED, ARCHETYPE, 2, ids[index], ids[index + 1], market)
    again = draw_pair(SEED, ARCHETYPE, 2, ids[index], ids[index + 1], market)
    assert first == again
    assert first[0].background and first[1].background


def test_the_pairs_differ_from_each_other(drawn: Path) -> None:
    drawn_ids = [h["household_id"] for h in households(drawn)]
    names = [{m["name"] for m in portfolio(drawn, h)["household_membership"]} for h in drawn_ids]
    assert all(len(n) == 2 for n in names)
    assert len(set().union(*names)) == 16
    balances = [v for h in drawn_ids for v in opening_balances(drawn, h).values()]
    assert len(set(balances)) == len(balances)


def test_the_trap_understates_the_basis_by_the_step_up_of_the_dead_spouses_half(drawn: Path) -> None:
    """Half of each joint lot takes its value on the day of death; the other half keeps half its cost."""
    registry = json.loads((drawn / "sealed" / "registry.json").read_text())["entries"]
    prices = {}
    with (drawn / "securities" / "prices_synthetic.csv").open() as handle:
        for row in csv.DictReader(handle):
            prices[(row["security_id"], row["valuation_date"])] = Decimal(row["price"])
    traps = [h["household_id"] for h in households(drawn) if h["role"] == "trap"]
    assert len(traps) == 4
    for household_id in traps:
        crm = json.loads((drawn / "households" / household_id / "crm" / "crm.json").read_text())
        died = next(a["refers_to"] for a in crm["activities"] if a["kind"] == "death_notification")
        joint = next(
            a["account_id"] for a in rows(drawn, household_id, "accounts.csv") if a["account_type"] == "joint_taxable"
        )
        lots = [
            lot
            for lot in rows(drawn, household_id, "tax_lots.csv")
            if lot["valuation_date"] == SCENARIO and lot["account_id"] == joint
        ]
        shown = sum((Decimal(lot["cost_basis"]) for lot in lots), Decimal(0))
        correct = Decimal(0)
        for lot in lots:
            cost, units = Decimal(lot["cost_basis"]), Decimal(lot["units"])
            kept = cost - (cost * HALF).quantize(CENT, rounding=ROUND_HALF_UP)
            stepped = (units * HALF * prices[(lot["security_id"], died)]).quantize(CENT, rounding=ROUND_HALF_UP)
            correct += kept + stepped
        entry = next(e for e in registry if e["household_id"] == household_id)
        assert figure(entry, "Basis the custodian shows") == usd(shown)
        assert figure(entry, f"Correct basis after the step-up on {died}") == usd(correct)
        assert figure(entry, "Basis understated") == usd(correct - shown).replace("$-", "-$")


def test_a_survivor_past_rmd_age_takes_the_2025_distribution_from_the_table(drawn: Path) -> None:
    """The 31 December 2024 balance over the Uniform Lifetime factor for the survivor's age at the end of 2025."""
    checked = 0
    for household in households(drawn):
        household_id = household["household_id"]
        data = portfolio(drawn, household_id)
        born = {m["person_id"]: date.fromisoformat(m["born"]) for m in data["household_membership"]}
        owners = {o["account_id"]: o["owner_ids"] for o in data["legal_ownership"]}
        balances = opening_balances(drawn, household_id)
        for account in rows(drawn, household_id, "accounts.csv"):
            if account["account_type"] != "traditional_ira":
                continue
            (owner,) = owners[account["account_id"]]
            if born[owner] > date(1952, 12, 31):
                continue
            factor = Decimal(UNIFORM_LIFETIME[2025 - born[owner].year])
            due = (balances[account["account_id"]] / factor).quantize(CENT, rounding=ROUND_HALF_UP)
            paid = [
                -Decimal(t["amount"])
                for t in rows(drawn, household_id, "transactions.csv")
                if t["type"] == "DISTRIBUTION" and t["account_id"] == account["account_id"]
            ]
            assert paid == [due]
            checked += 1
    assert checked >= 1
