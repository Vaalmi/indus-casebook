"""Archetype 3, the concentrated executive: RSU basis missing in the custodian's records."""

import csv
import dataclasses
import json
from decimal import Decimal
from pathlib import Path

import pytest

from casebook.build import build_book
from casebook.checks import check_book
from casebook.generate.script import AccountScript, Holding, HouseholdScript, load_scripts
from casebook.generate.simulate import simulate
from casebook.plant import PlantContext, PlantError, plant
from casebook.replay import replay
from casebook.securities.market import build_market
from casebook.securities.master import load_master
from casebook.sources.context import SNAPSHOT_DAYS

from .conftest import SCRIPTS, SEED

D = Decimal
ARCHETYPE = SCRIPTS / "archetype-3"
TRAP, TWIN = "HH-3058", "HH-3462"
EMPLOYER = "SEC-0028"
SCENARIO = "2026-04-15"


@pytest.fixture(scope="module")
def book(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("a03") / "book"
    build_book(SEED, out, ARCHETYPE)
    return out


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
    return {s.household.household_id: s for s in load_scripts(ARCHETYPE)}


def test_the_pair_passes_every_check_but_the_prices_check_on_the_trap(book: Path) -> None:
    failed = {(line.household_id, line.check) for line in check_book(book).lines if not line.passed}
    assert failed <= {(TRAP, "prices and values")}


def test_the_pair_passes_every_check_with_the_custodians_blank_rsu_price(book: Path) -> None:
    assert check_book(book).passed


def test_the_registry_figures_follow_from_the_source_files(book: Path) -> None:
    root = book / "households" / TRAP
    realized = rows(root / "custodian" / "realized_lots.csv")
    prices = {
        (r["security_id"], r["valuation_date"]): D(r["price"]) for r in rows(book / "securities/prices_synthetic.csv")
    }
    entry = next(
        e for e in json.loads((book / "sealed" / "registry.json").read_text())["entries"] if e["item_id"] == "PI-0004"
    )
    figures = dict((f["label"], f["value"]) for f in entry["figures"])
    # Worked by hand: the sale of 2025-12-12 closes the releases of 2025-02-20 and 2025-05-20,
    # 800 shares each, released at $216.06 and $229.90: 172,848.00 + 183,920.00 = 356,768.00 of
    # true basis. The custodian's realized lots show 0.00, so the gain is overstated by all of it.
    sold = [r for r in realized if r["security_id"] == EMPLOYER]
    assert [(r["acquired_date"], r["units"], r["cost_basis"]) for r in sold] == [
        ("2025-02-20", "800", "0.00"),
        ("2025-05-20", "800", "0.00"),
    ]
    true_basis = sum((D(r["units"]) * prices[(EMPLOYER, r["acquired_date"])] for r in sold), D(0))
    assert true_basis == D("356768.00")
    assert figures["Released shares sold"] == "1600"
    assert figures["Basis the custodian shows"] == "$0.00"
    assert figures["True basis"] == figures["Gain overstated"] == "$356,768.00"
    # The release confirmations in the CRM give the same values.
    summaries = [a["summary"] for a in json.loads((root / "crm" / "crm.json").read_text())["activities"]]
    assert any("$172,848.00" in s for s in summaries) and any("$183,920.00" in s for s in summaries)
    # The two releases still held, 2025-08-20 at $236.83 and 2025-11-20 at $274.64: 189,464.00 +
    # 219,712.00 = 409,176.00, which the custodian's tax lots show as 0.00.
    held = [
        r
        for r in rows(root / "custodian" / "tax_lots.csv")
        if r["valuation_date"] == SCENARIO and r["account_id"] == "SYN-30580002" and r["security_id"] == EMPLOYER
    ]
    assert {r["cost_basis"] for r in held} == {"0.00"}
    assert sum((D(r["units"]) * prices[(EMPLOYER, r["acquired_date"])] for r in held), D(0)) == D("409176.00")
    assert figures["Basis missing on released shares still held"] == "$409,176.00"
    # Concentration: employer stock's market value over all positions and cash on the scenario date.
    positions = [r for r in rows(root / "custodian" / "positions.csv") if r["valuation_date"] == SCENARIO]
    cash = [r for r in rows(root / "custodian" / "cash.csv") if r["valuation_date"] == SCENARIO]
    employer = sum((D(r["market_value"]) for r in positions if r["security_id"] == EMPLOYER), D(0))
    total = sum((D(r["market_value"]) for r in positions), D(0))
    total += sum((D(r["settled_cash"]) + D(r["unsettled_cash"]) for r in cash), D(0))
    share = (employer / total * 100).quantize(D("0.01"))
    assert share > 15
    assert figures["Bramwell Devices Group, share of the household on 2026-04-15"] == f"{share}%"
    assert figures["IPS concentration limit"] == "15.00%"


def test_a_trap_with_no_sale_of_released_shares_fails_the_build() -> None:
    trap = scripts()[TRAP]
    unsold = dataclasses.replace(trap, activity=tuple(a for a in trap.activity if a.kind != "sell"))
    with pytest.raises(PlantError, match="no released shares are sold"):
        plant(context(unsold))


def test_a_release_the_crm_does_not_confirm_fails_the_build() -> None:
    trap = scripts()[TRAP]
    hh = trap.household
    unconfirmed = dataclasses.replace(trap, household=dataclasses.replace(hh, crm_activities=hh.crm_activities[1:]))
    with pytest.raises(PlantError, match="no release confirmation in the CRM gives the 800 shares"):
        plant(context(unconfirmed))


def test_a_clean_twin_above_the_concentration_limit_fails_the_build() -> None:
    twin = scripts()[TWIN]
    joint = twin.accounts[0]
    old_shares = Holding("L-34620001-09", "SEC-0030", D("900000"), joint.holdings[0].acquired, D("40"))
    heavier = dataclasses.replace(
        twin, accounts=(AccountScript(joint.account_id, joint.cash, (*joint.holdings, old_shares)), *twin.accounts[1:])
    )
    with pytest.raises(PlantError, match=r"above the IPS concentration limit of 15\.00%"):
        plant(context(heavier))


def test_a_twin_that_is_not_clean_fails_the_build() -> None:
    twin = scripts()[TWIN]
    assert twin.twin is not None
    relabelled = dataclasses.replace(twin, twin=dataclasses.replace(twin.twin, kind="near_miss"))
    with pytest.raises(PlantError, match="archetype 3's twin is clean, not near_miss"):
        plant(context(relabelled))
