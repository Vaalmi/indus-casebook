"""Archetype 9, the cross-account tax-loss harvester: a replacement purchase in an IRA."""

import csv
import dataclasses
import json
import shutil
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
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
ARCHETYPE = SCRIPTS / "archetype-9"
TRAP, TWIN = "HH-9234", "HH-9571"
FUND = "SEC-0025"


@pytest.fixture(scope="module")
def book(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("a09") / "book"
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


def moved_buy(script: HouseholdScript, day: date) -> HouseholdScript:
    """The script with its IRA's purchase of the fund moved to `day`."""
    activity = tuple(
        dataclasses.replace(a, day=day) if a.kind == "buy" and a.security_id == FUND else a for a in script.activity
    )
    return dataclasses.replace(script, activity=tuple(sorted(activity, key=lambda a: a.day)))


def test_the_pair_passes_every_check(book: Path) -> None:
    report = check_book(book)
    assert report.passed, report.render()
    assert {line.household_id for line in report.lines} == {TRAP, TWIN}


def test_the_wash_sale_check_passes_on_the_trap_only_because_of_its_entry(book: Path, tmp_path: Path) -> None:
    copy = tmp_path / "book"
    shutil.copytree(book, copy)
    (copy / "sealed" / "registry.json").write_text(json.dumps({"entries": []}))
    failed = {(line.household_id, line.check) for line in check_book(copy).lines if not line.passed}
    assert failed == {(TRAP, "wash sales")}


def test_the_registry_figures_follow_from_the_source_files(book: Path) -> None:
    root = book / "households" / TRAP
    entry = next(
        e for e in json.loads((book / "sealed" / "registry.json").read_text())["entries"] if e["item_id"] == "PI-0010"
    )
    figures = dict((f["label"], f["value"]) for f in entry["figures"])
    (sold,) = [r for r in rows(root / "custodian" / "realized_lots.csv") if r["security_id"] == FUND]
    (bought,) = [
        t
        for t in rows(root / "custodian" / "transactions.csv")
        if t["type"] == "BUY" and t["security_id"] == FUND and t["account_id"] == "SYN-92340002"
    ]
    # Worked by hand: 847 units bought at 116% of the 2024-12-31 price of 283.02 cost
    # 847 x 283.02 x 1.16 = 278,072.81; sold on 2025-11-03 at 265.12 for 224,556.64; a loss of
    # 53,516.17. The IRA buys 500 units on 2025-11-19, 16 days later, so 500 of the 847 units are
    # replaced and 53,516.17 x 500 / 847 = 31,591.60 of the loss is disallowed, 21,924.57 allowed.
    assert (sold["sold_date"], sold["units"], sold["cost_basis"], sold["proceeds"]) == (
        "2025-11-03",
        "847",
        "278072.81",
        "224556.64",
    )
    assert (bought["trade_date"], bought["units"]) == ("2025-11-19", "500")
    assert (date.fromisoformat(bought["trade_date"]) - date.fromisoformat(sold["sold_date"])).days <= 30
    loss = D(sold["cost_basis"]) - D(sold["proceeds"])
    disallowed = (loss * D(bought["units"]) / D(sold["units"])).quantize(D("0.01"), rounding=ROUND_HALF_UP)
    assert (loss, disallowed) == (D("53516.17"), D("31591.60"))
    assert figures == {
        "Loss on the sale": "$53,516.17",
        "Units sold": "847",
        "Units replaced": "500",
        "Disallowed loss": "$31,591.60",
        "Allowed loss": "$21,924.57",
    }
    assert {sold["transaction_id"], bought["transaction_id"]} <= set(entry["references"])


def test_a_trap_whose_replacement_falls_outside_the_window_fails_the_build() -> None:
    late = moved_buy(scripts()[TRAP], date(2025, 12, 4))
    with pytest.raises(
        PlantError, match="0 loss sales have a purchase of the same security in a related IRA within 30"
    ):
        plant(context(late))


def test_a_near_miss_bought_back_on_the_30th_day_fails_the_build() -> None:
    inside = moved_buy(scripts()[TWIN], date(2025, 12, 3))
    with pytest.raises(PlantError, match="30 days from the loss sale on 2025-11-03, inside the 30-day window"):
        plant(context(inside))


def test_a_near_miss_that_never_buys_back_fails_the_build() -> None:
    twin = scripts()[TWIN]
    never = dataclasses.replace(
        twin, activity=tuple(a for a in twin.activity if a.security_id != FUND or a.kind == "sell")
    )
    with pytest.raises(PlantError, match="a near miss sells at a loss and buys the security back"):
        plant(context(never))


def test_the_item_is_known_once_both_the_sale_and_the_replacement_are_on_record() -> None:
    # Reviewer A, slice 5 targeted check: a replacement bought before the loss sale dated the item by
    # the purchase alone, so a note between the two could cite the disallowed loss.
    trap = next(s for s in load_scripts(SCRIPTS / "archetype-9") if s.role == "trap")
    early = tuple(
        dataclasses.replace(a, day=date(2025, 10, 27)) if a.kind == "buy" and a.day == date(2025, 11, 19) else a
        for a in trap.activity
    )
    moved = dataclasses.replace(trap, activity=early)
    entry = plant(context(moved)).entries[0]
    assert entry.known_as_of == date(2025, 11, 3)
