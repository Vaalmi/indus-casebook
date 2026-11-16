"""Archetype 2: a December sale pushes modified AGI over the NIIT threshold, its workings recomputed from the files."""

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
PAIR = SCRIPTS / "archetype-2"
JOINT = "SYN-23160001"


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


def with_sale(script: HouseholdScript, units: str) -> HouseholdScript:
    activity = tuple(dataclasses.replace(a, units=D(units)) if a.kind == "sell" else a for a in script.activity)
    return dataclasses.replace(script, activity=activity)


@pytest.fixture(scope="module")
def pair_book(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("archetype-2") / "book"
    build_book(SEED, out, PAIR)
    return out


def test_the_pair_builds_and_passes_every_check(pair_book: Path) -> None:
    report = check_book(pair_book)
    assert {line.household_id for line in report.lines} == {"HH-2316", "HH-2749"}
    assert report.passed, report.render()


def test_the_niit_workings_follow_from_the_source_files(pair_book: Path) -> None:
    root = pair_book / "households" / "HH-2316"
    dividends = [
        D(t["amount"])
        for t in rows(root / "custodian" / "transactions.csv")
        if t["type"] == "DIVIDEND" and t["account_id"] == JOINT and t["trade_date"].startswith("2025-")
    ]
    realized = [
        D(r["proceeds"]) - D(r["cost_basis"])
        for r in rows(root / "custodian" / "realized_lots.csv")
        if r["account_id"] == JOINT and r["sold_date"].startswith("2025-")
    ]
    w2s = [a["summary"] for a in json.loads((root / "crm" / "crm.json").read_text())["activities"]]
    # What the files show: 16 dividends in the joint account in 2025 (SEC-0002 1,933.78, SEC-0010
    # 1,771.89, SEC-0018 6,706.86, SEC-0019 3,071.14), one sale (proceeds 103,292.00 less basis
    # 28,353.28), and W-2 wages of $141,500.00 and $87,000.00 in the CRM.
    assert len(dividends) == 16
    assert sum(dividends, D(0)) == D("13483.67")
    assert realized == [D("74938.72")]
    assert any("$141,500.00" in s and "$87,000.00" in s for s in w2s)
    # By hand: NII = 13,483.67 + 74,938.72 = 88,422.39; MAGI = 228,500.00 + 88,422.39 = 316,922.39;
    # over the $250,000 joint threshold by 66,922.39, less than NII; NIIT = 0.038 x 66,922.39 =
    # 2,543.05082 -> 2,543.05. Without the sale's gain MAGI is 316,922.39 - 74,938.72 = 241,983.67.
    entry = json.loads((pair_book / "sealed" / "registry.json").read_text())["entries"][0]
    assert entry["item_id"] == "PI-0003"
    figures = {f["label"]: f["value"] for f in entry["figures"]}
    assert figures == {
        "Net investment income": "$88,422.39",
        "Modified AGI": "$316,922.39",
        "Over the threshold": "$66,922.39",
        "Net investment income tax": "$2,543.05",
    }
    workings = dict(entry["table"]["rows"])
    assert workings["SALT deduction limit"] == "$40,000.00"
    assert workings["Bond fund dividends in the taxable accounts"] == "$6,706.86"
    assert "$241,983.67" in entry["justified_conclusion"]
    assert "IRC § 1411" in entry["justified_conclusion"]


def test_a_sale_too_small_to_cross_the_threshold_fails_the_build() -> None:
    small = with_sale(scripts()["HH-2316"], "20")
    with pytest.raises(PlantError, match="is not over the"):
        plant(context(small))


def test_wages_over_the_threshold_without_the_sale_fail_the_build() -> None:
    trap = scripts()["HH-2316"]
    income = tuple(dataclasses.replace(i, amount=i.amount + D(30000)) for i in trap.household.income)
    raised = dataclasses.replace(trap, household=dataclasses.replace(trap.household, income=income))
    with pytest.raises(PlantError, match="over the threshold without the sale"):
        plant(context(raised))


def test_a_near_miss_over_the_threshold_fails_the_build() -> None:
    large = with_sale(scripts()["HH-2749"], "400")
    with pytest.raises(PlantError, match=r"under the .* threshold by at most"):
        plant(context(large))


def test_a_near_miss_far_under_the_threshold_fails_the_build() -> None:
    twin = scripts()["HH-2749"]
    income = tuple(dataclasses.replace(i, amount=i.amount - D(20000)) for i in twin.household.income)
    lowered = dataclasses.replace(twin, household=dataclasses.replace(twin.household, income=income))
    with pytest.raises(PlantError, match=r"under the .* threshold by at most"):
        plant(context(lowered))
