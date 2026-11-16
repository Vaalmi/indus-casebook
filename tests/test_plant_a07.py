"""Archetype 7, an inherited IRA under the ten-year rule: the held-out pair builds clean from the
private folder, and the registry's figures follow from the emitted files, worked by hand.

The pair lives in $CASEBOOK_PRIVATE until the freeze, and so does `expected.json` beside it: the
hand-worked figures, with their working, kept out of this public file so the answer is not
published before the pair is. These tests skip where the folder is absent (CI).
"""

import csv
import dataclasses
import json
import os
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.build import build_book
from casebook.checks import check_book
from casebook.generate.script import Activity, HouseholdScript, load_scripts
from casebook.generate.simulate import simulate
from casebook.plant import PlantContext, PlantError, plant
from casebook.replay import replay
from casebook.securities.market import build_market
from casebook.securities.master import load_master
from casebook.sources.context import SNAPSHOT_DAYS

from .conftest import SEED

D = Decimal
PAIR = Path(os.environ.get("CASEBOOK_PRIVATE", "/nonexistent")) / "book" / "scripted" / "archetype-7"
pytestmark = pytest.mark.skipif(
    not PAIR.is_dir(), reason="the held-out pair for archetype 7 lives in $CASEBOOK_PRIVATE, absent here"
)
INHERITED = "inherited_ira"
PAID_OUT = ("DISTRIBUTION", "QCD", "WITHDRAWAL")


def expected() -> dict[str, Any]:
    return json.loads((PAIR / "expected.json").read_text())


def context(script: HouseholdScript) -> PlantContext:
    market = build_market(load_master(), SEED)
    simulation = simulate(script, market)
    return PlantContext(
        script, simulation.events, replay(simulation.events, SNAPSHOT_DAYS), simulation.quarters, market
    )


def rows(path: Path) -> list[dict[str, str]]:
    with path.open() as handle:
        return list(csv.DictReader(handle))


def script(role: str) -> HouseholdScript:
    return next(s for s in load_scripts(PAIR) if s.role == role)


def balance(root: Path, account_id: str, day: str) -> Decimal:
    """Positions plus cash in the custodian's files, for one account on one day."""
    held = [
        p
        for p in rows(root / "custodian" / "positions.csv")
        if (p["account_id"], p["valuation_date"]) == (account_id, day)
    ]
    cash = [
        c for c in rows(root / "custodian" / "cash.csv") if (c["account_id"], c["valuation_date"]) == (account_id, day)
    ]
    return sum((D(p["market_value"]) for p in held), D(0)) + sum(
        (D(c["settled_cash"]) + D(c["unsettled_cash"]) for c in cash), D(0)
    )


def paid_out(root: Path, account_id: str) -> list[dict[str, str]]:
    return [
        t
        for t in rows(root / "custodian" / "transactions.csv")
        if t["account_id"] == account_id and t["type"] in PAID_OUT
    ]


def born_on(script: HouseholdScript, born: str) -> HouseholdScript:
    """The script with the inherited IRA's decedent born on another day."""
    hh = script.household
    accounts = tuple(
        dataclasses.replace(a, inherited_from=dataclasses.replace(a.inherited_from, born=date.fromisoformat(born)))
        if a.inherited_from is not None
        else a
        for a in hh.accounts
    )
    return dataclasses.replace(script, household=dataclasses.replace(hh, accounts=accounts))


@pytest.fixture(scope="module")
def book(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("a07") / "book"
    build_book(SEED, out, PAIR, held_out=True)
    return out


def test_the_pair_passes_every_check(book: Path) -> None:
    report = check_book(book)
    pair = expected()
    assert {line.household_id for line in report.lines} == {pair["trap"]["household_id"], pair["twin"]["household_id"]}
    assert report.passed, report.render()


def test_the_trap_figures_follow_from_the_source_files(book: Path) -> None:
    trap = expected()["trap"]
    root = book / "households" / trap["household_id"]
    account = trap["account_id"]
    assert balance(root, account, "2024-12-31") == D(trap["balance_2024_12_31"])
    assert balance(root, account, "2025-12-31") == D(trap["balance_2025_12_31"])
    assert paid_out(root, account) == []
    accounts = {a["account_id"]: a for a in rows(root / "custodian" / "accounts.csv")}
    assert accounts[account]["account_type"] == INHERITED
    assert trap["decedent"] in accounts[account]["registration"]
    crm = json.loads((root / "crm" / "crm.json").read_text())
    assert any(trap["death_record"] in a["summary"] for a in crm["activities"])
    entry = json.loads((book / "sealed" / "registry.json").read_text())["entries"][0]
    assert (entry["item_id"], entry["kind"]) == (trap["item_id"], "situation")
    assert {f["label"]: f["value"] for f in entry["figures"]} == trap["figures"]
    workings = dict(entry["table"]["rows"])
    for label, value in (trap["beneficiary_period"], trap["decedent_period"]):
        assert workings[label] == value


def test_the_twin_dies_before_the_required_beginning_date(book: Path) -> None:
    twin = expected()["twin"]
    root = book / "households" / twin["household_id"]
    crm = json.loads((root / "crm" / "crm.json").read_text())
    assert any(twin["death_record"] in a["summary"] for a in crm["activities"])
    assert paid_out(root, twin["account_id"]) == []
    entries = json.loads((book / "sealed" / "registry.json").read_text())["entries"]
    assert [e for e in entries if e["household_id"] == twin["household_id"]] == []


def test_a_death_before_the_required_beginning_date_is_no_trap() -> None:
    trap = expected()["trap"]
    changed = born_on(script("trap"), trap["a_younger_decedent_born"])
    with pytest.raises(PlantError, match=f"before the required beginning date {trap['its_required_beginning_date']}"):
        plant(context(changed))


def test_an_rmd_taken_in_2025_is_no_trap() -> None:
    trap = expected()["trap"]
    rmd = trap["figures"]["2025 RMD"]
    amount = D(rmd.removeprefix("$").replace(",", ""))
    paid = Activity("rmd", date(2025, 12, 1), trap["account_id"], amount=amount, tax_year=2025, withheld=D(0))
    original = script("trap")
    with pytest.raises(PlantError, match=re.escape(f"{rmd} was taken in 2025")):
        plant(context(dataclasses.replace(original, activity=(*original.activity, paid))))


def test_a_twin_whose_parent_died_after_the_required_beginning_date_is_refused() -> None:
    twin = expected()["twin"]
    changed = born_on(script("twin"), twin["an_older_decedent_born"])
    with pytest.raises(
        PlantError, match=f"on or after the required beginning date {twin['its_required_beginning_date']}"
    ):
        plant(context(changed))
