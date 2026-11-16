"""Archetype 4: a Roth conversion from an IRA with basis, its Form 8606 recomputed from the emitted files."""

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
from casebook.model.household import IraBasis
from casebook.plant import PlantContext, PlantError, plant
from casebook.replay import replay
from casebook.securities.market import build_market
from casebook.securities.master import load_master
from casebook.sources.context import SNAPSHOT_DAYS

from .conftest import SCRIPTS, SEED

D = Decimal
PAIR = SCRIPTS / "archetype-4"
IRA = "SYN-41050002"
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


def with_basis(script: HouseholdScript, basis: str) -> HouseholdScript:
    hh = script.household
    profile = dataclasses.replace(
        hh.tax_profile, ira_basis=tuple(IraBasis(b.person_id, D(basis)) for b in hh.tax_profile.ira_basis)
    )
    return dataclasses.replace(script, household=dataclasses.replace(hh, tax_profile=profile))


@pytest.fixture(scope="module")
def pair_book(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("archetype-4") / "book"
    build_book(SEED, out, PAIR)
    return out


def test_the_pair_builds_and_passes_every_check(pair_book: Path) -> None:
    report = check_book(pair_book)
    assert {line.household_id for line in report.lines} == {"HH-4105", "HH-4633"}
    assert report.passed, report.render()


def test_the_form_8606_figures_follow_from_the_source_files(pair_book: Path) -> None:
    root = pair_book / "households" / "HH-4105"
    iras = [
        a["account_id"] for a in rows(root / "custodian" / "accounts.csv") if a["account_type"] == "traditional_ira"
    ]
    assert iras == [IRA]
    held = [
        D(p["market_value"])
        for p in rows(root / "custodian" / "positions.csv")
        if p["valuation_date"] == YEAR_END and p["account_id"] == IRA
    ]
    cash = [
        D(c["settled_cash"]) + D(c["unsettled_cash"])
        for c in rows(root / "custodian" / "cash.csv")
        if c["valuation_date"] == YEAR_END and c["account_id"] == IRA
    ]
    converted = [
        -D(t["amount"])
        for t in rows(root / "custodian" / "transactions.csv")
        if t["type"] == "CONVERSION_OUT" and t["account_id"] == IRA
    ]
    profile = json.loads((root / "portfolio" / "tax_profile.json").read_text())
    # What the files show: on 31 December 2025 the IRA holds 716 SEC-0001 at 275.37 ($197,164.92),
    # 318 SEC-0013 at 283.59 ($90,181.62), 428 SEC-0018 at 234.01 ($100,156.28) and $5,208.54 cash;
    # one $60,000.00 conversion; $38,500.00 of basis carried from the 2024 return.
    assert sorted(held) == [D("90181.62"), D("100156.28"), D("197164.92")]
    assert cash == [D("5208.54")]
    assert converted == [D("60000.00")]
    assert [D(b["basis"]) for b in profile["ira_basis"]] == [D("38500.00")]
    # By hand: line 6 = 197,164.92 + 90,181.62 + 100,156.28 + 5,208.54 = 392,711.36;
    # line 9 = 392,711.36 + 60,000 = 452,711.36; line 10 = 38,500 / 452,711.36 = 0.08504 -> 0.085;
    # line 11 = 60,000 x 0.085 = 5,100.00; line 18 = 60,000 - 5,100 = 54,900.00;
    # line 14 = 38,500 - 5,100 = 33,400.00.
    entry = json.loads((pair_book / "sealed" / "registry.json").read_text())["entries"][0]
    assert entry["item_id"] == "PI-0005"
    lines = {line: amount for line, _what, amount in entry["table"]["rows"]}
    assert lines["1"] == "$0.00"
    assert lines["2"] == lines["5"] == "$38,500.00"
    assert lines["6"] == "$392,711.36"
    assert lines["9"] == "$452,711.36"
    assert lines["10"] == "0.085"
    assert lines["11"] == lines["17"] == "$5,100.00"
    assert lines["18"] == "$54,900.00"
    assert lines["14"] == "$33,400.00"
    assert "IRC § 408(d)(2)" in entry["justified_conclusion"]


def test_a_conversion_with_no_basis_fails_the_build() -> None:
    with pytest.raises(PlantError, match="carries no IRA basis"):
        plant(context(with_basis(scripts()["HH-4105"], "0.00")))


def test_basis_covering_the_whole_conversion_fails_the_build() -> None:
    with pytest.raises(PlantError, match="covers the whole conversion"):
        plant(context(with_basis(scripts()["HH-4105"], "500000.00")))


def test_an_unresolved_twin_with_basis_on_file_fails_the_build() -> None:
    with pytest.raises(PlantError, match="no IRA basis on file"):
        plant(context(with_basis(scripts()["HH-4633"], "38500.00")))


def test_an_unresolved_twin_without_the_clients_claim_fails_the_build() -> None:
    twin = scripts()["HH-4633"]
    kept = tuple(a for a in twin.household.crm_activities if "nondeductible" not in a.summary)
    silent = dataclasses.replace(twin, household=dataclasses.replace(twin.household, crm_activities=kept))
    with pytest.raises(PlantError, match="CRM record of nondeductible contributions"):
        plant(context(silent))


def test_the_twin_must_be_unresolved_as_its_script_says() -> None:
    twin = scripts()["HH-4633"]
    assert twin.twin is not None
    clean = dataclasses.replace(twin, twin=dataclasses.replace(twin.twin, kind="clean"))
    with pytest.raises(PlantError, match="unresolved"):
        plant(context(clean))
