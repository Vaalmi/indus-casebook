"""Archetype 1: the backdoor Roth taxed pro rata, its figures recomputed from the emitted files."""

import csv
import dataclasses
import json
from decimal import Decimal
from pathlib import Path

import pytest

from casebook.build import build_book
from casebook.checks import check_book
from casebook.generate.script import HouseholdScript, load_scripts
from casebook.generate.simulate import simulate
from casebook.plant import PlantContext, PlantError, plant
from casebook.replay import replay
from casebook.securities.market import build_market
from casebook.securities.master import load_master
from casebook.sources.context import SNAPSHOT_DAYS

from .conftest import SCRIPTS, SEED

D = Decimal
PAIR = SCRIPTS / "archetype-1"
YEAR_END = "2025-12-31"


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


def with_account(script: HouseholdScript, account_id: str, **changes: str) -> HouseholdScript:
    accounts = tuple(
        dataclasses.replace(a, **changes) if a.account_id == account_id else a for a in script.household.accounts
    )
    return dataclasses.replace(script, household=dataclasses.replace(script.household, accounts=accounts))


@pytest.fixture(scope="module")
def pair_book(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("archetype-1") / "book"
    build_book(SEED, out, PAIR)
    return out


def test_the_pair_builds_and_passes_every_check(pair_book: Path) -> None:
    report = check_book(pair_book)
    assert {line.household_id for line in report.lines} == {"HH-1204", "HH-1587"}
    assert report.passed, report.render()


def test_the_form_8606_figures_follow_from_the_source_files(pair_book: Path) -> None:
    root = pair_book / "households" / "HH-1204"
    accounts = rows(root / "custodian" / "accounts.csv")
    iras = {a["account_id"] for a in accounts if a["account_type"] == "traditional_ira" and a["owners"] == "Luka Kovac"}
    assert iras == {"SYN-12040002", "SYN-12040003"}
    value = sum(
        (
            D(p["market_value"])
            for p in rows(root / "custodian" / "positions.csv")
            if p["valuation_date"] == YEAR_END and p["account_id"] in iras
        ),
        D(0),
    ) + sum(
        (
            D(c["settled_cash"]) + D(c["unsettled_cash"])
            for c in rows(root / "custodian" / "cash.csv")
            if c["valuation_date"] == YEAR_END and c["account_id"] in iras
        ),
        D(0),
    )
    transactions = rows(root / "custodian" / "transactions.csv")
    contributed = [D(t["amount"]) for t in transactions if t["type"] == "CONTRIBUTION" and t["account_id"] in iras]
    converted = [-D(t["amount"]) for t in transactions if t["type"] == "CONVERSION_OUT" and t["account_id"] in iras]
    profile = json.loads((root / "portfolio" / "tax_profile.json").read_text())
    basis = [D(b["basis"]) for b in profile["ira_basis"] if b["person_id"] == "P-1204-2"]
    # What the files show: a $7,000.00 contribution and a $7,000.00 conversion, no basis carried in,
    # and on 31 December 2025 the rollover IRA holding 502 SEC-0013 at 283.59 ($142,362.18), 121
    # SEC-0003 at 354.31 ($42,871.51) and $2,311.23 cash, with the new IRA empty.
    assert (contributed, converted, basis) == ([D("7000.00")], [D("7000.00")], [D("0.00")])
    assert value == D("187544.92")  # 142,362.18 + 42,871.51 + 2,311.23
    # By hand: line 5 = 7,000 + 0 = 7,000; line 9 = 187,544.92 + 0 + 7,000 = 194,544.92;
    # line 10 = 7,000 / 194,544.92 = 0.03598 -> 0.036; line 11 = 7,000 x 0.036 = 252.00;
    # line 18 = 7,000 - 252 = 6,748.00; line 14 = 7,000 - 252 = 6,748.00.
    entry = json.loads((pair_book / "sealed" / "registry.json").read_text())["entries"][0]
    assert entry["item_id"] == "PI-0002"
    lines = {line: amount for line, _what, amount in entry["table"]["rows"]}
    assert lines["6"] == "$187,544.92"
    assert lines["9"] == "$194,544.92"
    assert lines["10"] == "0.036"
    assert lines["11"] == lines["17"] == "$252.00"
    assert lines["18"] == "$6,748.00"
    assert lines["14"] == "$6,748.00"
    figures = {f["label"]: f["value"] for f in entry["figures"]}
    assert figures["Taxable amount (Form 8606 line 18)"] == "$6,748.00"
    assert "IRC § 408(d)(2)" in entry["justified_conclusion"]
    assert "T-1204-0005" in entry["references"] and "T-1204-0006" in entry["references"]


def test_without_a_rollover_ira_the_trap_fails_the_build() -> None:
    trap = scripts()["HH-1204"]
    no_rollover = with_account(trap, "SYN-12040002", registration="Traditional IRA, Luka Kovac")
    with pytest.raises(PlantError, match="no rollover IRA"):
        plant(context(no_rollover))


def test_a_contribution_above_the_limit_fails_the_build() -> None:
    trap = scripts()["HH-1204"]
    activity = tuple(
        dataclasses.replace(a, amount=D("9000.00"))
        if a.kind == "contribution" and a.account_id == "SYN-12040003"
        else a
        for a in trap.activity
    )
    with pytest.raises(PlantError, match="above the IRA contribution limit"):
        plant(context(dataclasses.replace(trap, activity=activity)))


def test_a_near_miss_with_its_pre_tax_money_in_an_ira_fails_the_build() -> None:
    twin = scripts()["HH-1587"]
    rolled = with_account(twin, "SYN-15870002", account_type="traditional_ira", registration="Rollover IRA")
    with pytest.raises(PlantError, match="large pre-tax balance outside IRAs"):
        plant(context(rolled))


def test_a_near_miss_with_money_left_in_its_traditional_ira_fails_the_build() -> None:
    twin = scripts()["HH-1587"]
    activity = tuple(
        dataclasses.replace(a, amount=D("6000.00")) if a.kind == "roth_conversion" else a for a in twin.activity
    )
    with pytest.raises(PlantError, match="no traditional IRA value at year end"):
        plant(context(dataclasses.replace(twin, activity=activity)))


def test_the_twin_must_be_the_near_miss_its_script_says() -> None:
    twin = scripts()["HH-1587"]
    assert twin.twin is not None
    clean = dataclasses.replace(twin, twin=dataclasses.replace(twin.twin, kind="clean"))
    with pytest.raises(PlantError, match="near miss"):
        plant(context(clean))
