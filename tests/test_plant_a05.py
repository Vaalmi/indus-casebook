"""Archetype 5, the first RMD across two IRAs and a 401(k): the pair builds clean, and the
registry's figures follow from the emitted files, worked by hand."""

import csv
import dataclasses
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

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

from .conftest import SCRIPTS, SEED

D = Decimal
PAIR = SCRIPTS / "archetype-5"


def context(script: HouseholdScript) -> PlantContext:
    market = build_market(load_master(), SEED)
    simulation = simulate(script, market)
    return PlantContext(
        script, simulation.events, replay(simulation.events, SNAPSHOT_DAYS), simulation.quarters, market
    )


def rows(path: Path) -> list[dict[str, str]]:
    with path.open() as handle:
        return list(csv.DictReader(handle))


def scripts() -> dict[str, HouseholdScript]:
    return {s.household.household_id: s for s in load_scripts(PAIR)}


@pytest.fixture(scope="module")
def book(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("a05") / "book"
    build_book(SEED, out, PAIR)
    return out


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


def test_the_pair_passes_every_check(book: Path) -> None:
    report = check_book(book)
    assert {line.household_id for line in report.lines} == {"HH-5271", "HH-5814"}
    assert report.passed, report.render()


def test_the_trap_figures_follow_from_the_source_files(book: Path) -> None:
    root = book / "households" / "HH-5271"
    # Teodoro Villanueva, born 1952-03-14, is 73 on his 2025 birthday: Uniform Lifetime factor 26.5
    # (IRS Publication 590-B, Table III). The 31 December 2024 balances, positions plus cash:
    #   SYN-52710002  $623,678.60 / 26.5 = $23,535.0415 -> $23,535.04
    #   SYN-52710003  $210,343.76 / 26.5 =  $7,937.5004 ->  $7,937.50
    #   SYN-52710004  $337,343.96 / 26.5 = $12,729.9607 -> $12,729.96 (the 401(k))
    # The IRAs owe $31,472.54 together; $44,202.50 (all three added) was paid from SYN-52710002.
    assert balance(root, "SYN-52710002", "2024-12-31") == D("623678.60")
    assert balance(root, "SYN-52710003", "2024-12-31") == D("210343.76")
    assert balance(root, "SYN-52710004", "2024-12-31") == D("337343.96")
    paid = [
        (t["account_id"], t["amount"])
        for t in rows(root / "custodian" / "transactions.csv")
        if t["type"] == "DISTRIBUTION"
    ]
    assert paid == [("SYN-52710002", "-44202.50")]
    entry = json.loads((book / "sealed" / "registry.json").read_text())["entries"][0]
    assert entry["item_id"] == "PI-0006"
    assert {f["label"]: f["value"] for f in entry["figures"]} == {
        "2025 RMD, IRAs together": "$31,472.54",
        "Taken from the IRAs": "$44,202.50",
        "2025 RMD, 401(k)": "$12,729.96",
        "Taken from the 401(k)": "$0.00",
        "401(k) RMD missed": "$12,729.96",
        "Required beginning date": "2026-04-01",
    }
    assert [r[5] for r in entry["table"]["rows"]] == ["$23,535.04", "$7,937.50", "$12,729.96"]
    assert set(entry["references"]) == {"P-5271-1", "SYN-52710002", "SYN-52710003", "SYN-52710004", "T-5271-0044"}


def test_the_twin_meets_each_requirement_in_the_source_files(book: Path) -> None:
    root = book / "households" / "HH-5814"
    # Prema Raghavan, born 1952-07-22, factor 26.5 as above:
    #   SYN-58140002  $582,446.94 / 26.5 = $21,979.13; SYN-58140003 $194,775.76 / 26.5 = $7,350.03;
    #   together $29,329.16, paid from SYN-58140002. SYN-58140004 (401(k)) $311,957.24 / 26.5 = $11,771.97,
    #   paid from the 401(k). SYN-58140003 pays nothing, which aggregation allows.
    assert balance(root, "SYN-58140002", "2024-12-31") == D("582446.94")
    assert balance(root, "SYN-58140003", "2024-12-31") == D("194775.76")
    assert balance(root, "SYN-58140004", "2024-12-31") == D("311957.24")
    paid = {
        t["account_id"]: t["amount"]
        for t in rows(root / "custodian" / "transactions.csv")
        if t["type"] == "DISTRIBUTION"
    }
    assert paid == {"SYN-58140002": "-29329.16", "SYN-58140004": "-11771.97"}
    assert not [
        e
        for e in json.loads((book / "sealed" / "registry.json").read_text())["entries"]
        if e["household_id"] == "HH-5814"
    ]


def test_a_401k_that_paid_its_own_rmd_is_no_trap() -> None:
    trap = scripts()["HH-5271"]
    paid = Activity("rmd", date(2025, 12, 10), "SYN-52710004", amount=D("12729.96"), tax_year=2025, withheld=D(0))
    with pytest.raises(PlantError, match=re.escape("every 401(k) paid its own 2025 RMD")):
        plant(context(dataclasses.replace(trap, activity=(*trap.activity, paid))))


def test_an_owner_whose_first_year_is_not_2025_is_no_trap() -> None:
    trap = scripts()["HH-5271"]
    hh = trap.household
    older = dataclasses.replace(hh.members[0], born=date(1951, 3, 14))
    changed = dataclasses.replace(trap, household=dataclasses.replace(hh, members=(older, *hh.members[1:])))
    with pytest.raises(PlantError, match="2025 is not the first distribution year"):
        plant(context(changed))


def test_a_twin_whose_401k_paid_nothing_is_refused() -> None:
    twin = scripts()["HH-5814"]
    kept = tuple(a for a in twin.activity if not (a.kind == "rmd" and a.account_id == "SYN-58140004"))
    with pytest.raises(PlantError, match=re.escape("401(k) SYN-58140004 paid $0.00 of its $11,771.97 RMD")):
        plant(context(dataclasses.replace(twin, activity=kept)))


def test_a_twin_where_every_ira_paid_is_not_a_near_miss() -> None:
    twin = scripts()["HH-5814"]
    rollover = Activity("rmd", date(2025, 12, 5), "SYN-58140003", amount=D("100.00"), tax_year=2025, withheld=D(0))
    with pytest.raises(PlantError, match="nothing looks skipped"):
        plant(context(dataclasses.replace(twin, activity=(*twin.activity, rollover))))
