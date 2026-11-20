"""Archetype 8, the recently widowed investor: the step-up lagging at the custodian; a stale beneficiary.

The pair was held out in $CASEBOOK_PRIVATE until the freeze; the freeze moved it, and `expected.json`
beside it (the hand-worked figures and the pair's names and IDs), into `book/scripted/archetype-8`.
"""

import csv
import dataclasses
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.build import build_book
from casebook.checks import check_book
from casebook.generate.script import HouseholdScript, load_scripts
from casebook.generate.simulate import simulate
from casebook.model.household import Beneficiary
from casebook.plant import PlantContext, PlantError, plant
from casebook.replay import replay
from casebook.securities.market import build_market
from casebook.securities.master import load_master
from casebook.sources.context import SNAPSHOT_DAYS

from .conftest import ROOT, SEED

D = Decimal
PAIR = ROOT / "book" / "scripted" / "archetype-8"
SCENARIO = "2026-04-15"


def expected() -> dict[str, Any]:
    return json.loads((PAIR / "expected.json").read_text())


@pytest.fixture(scope="module")
def book(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("a08") / "book"
    build_book(SEED, out, PAIR, held_out=True)
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


def script(role: str) -> HouseholdScript:
    return next(s for s in load_scripts(PAIR) if s.role == role)


def half_up(value: Decimal) -> Decimal:
    return value.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def test_the_pair_passes_every_check(book: Path) -> None:
    report = check_book(book)
    assert report.passed, report.render()
    assert {line.household_id for line in report.lines} == {
        expected()["trap"]["household_id"],
        expected()["twin"]["household_id"],
    }


def test_the_registry_figures_follow_from_the_source_files(book: Path) -> None:
    trap = expected()["trap"]
    root = book / "households" / trap["household_id"]
    prices = {
        (r["security_id"], r["valuation_date"]): D(r["price"]) for r in rows(book / "securities/prices_synthetic.csv")
    }
    entry = next(
        e
        for e in json.loads((book / "sealed" / "registry.json").read_text())["entries"]
        if e["item_id"] == trap["item_id"]
    )
    figures = dict((f["label"], f["value"]) for f in entry["figures"])
    lots = [
        r
        for r in rows(root / "custodian" / "tax_lots.csv")
        if r["valuation_date"] == SCENARIO and r["account_id"] == trap["joint_account"]
    ]
    assert lots
    assert not [t for t in rows(root / "custodian" / "transactions.csv") if t["type"] == "STEP_UP"]
    # Each lot's correct basis: the survivor's half keeps its cost, the decedent's half steps up to
    # its value on the day of death (worked by hand for the first lot in expected.json).
    shown = correct = D(0)
    table = {r[0]: r for r in entry["table"]["rows"]}
    for lot in lots:
        cost, units = D(lot["cost_basis"]), D(lot["units"])
        right = cost - half_up(cost / 2) + half_up(units / 2 * prices[(lot["security_id"], trap["died"])])
        assert table[lot["lot_id"]][6] == f"${right:,.2f}"
        shown += cost
        correct += right
    assert list(table[trap["first_lot"]][3:]) == trap["first_lot_row"]
    assert figures["Basis the custodian shows"] == f"${shown:,.2f}"
    assert figures[f"Correct basis after the step-up on {trap['died']}"] == f"${correct:,.2f}"
    assert figures["Basis understated"] == f"${correct - shown:,.2f}"
    # The stale designation is in the custodian's beneficiaries file, naming the dead spouse.
    named = [b for b in rows(root / "custodian" / "beneficiaries.csv") if b["designation"] == "primary"]
    assert [[b["account_id"], b["name"], b["person_id"]] for b in named] == [trap["stale_primary"]]
    died = {
        m["person_id"]: m.get("died")
        for m in json.loads((root / "portfolio" / "household.json").read_text())["household_membership"]
    }
    assert died[trap["stale_primary"][2]] == trap["died"]
    label, value = trap["stale_figure"]
    assert figures[label] == value


def test_a_trap_whose_survivor_named_new_beneficiaries_fails_the_build() -> None:
    trap, spec = script("trap"), expected()["trap"]
    hh = trap.household
    children = tuple(
        Beneficiary(account, "primary", name, relationship, D(50), None, hh.configured)
        for account, name, relationship in spec["new_beneficiaries"]
    )
    updated = dataclasses.replace(trap, household=dataclasses.replace(hh, beneficiaries=children))
    with pytest.raises(PlantError, match=spec["refusals"]["named_new"]):
        plant(context(updated))


def test_a_trap_whose_death_the_crm_does_not_record_fails_the_build() -> None:
    trap, spec = script("trap"), expected()["trap"]
    silent = dataclasses.replace(trap, household=dataclasses.replace(trap.household, crm_activities=()))
    with pytest.raises(PlantError, match=spec["refusals"]["no_death_record"]):
        plant(context(silent))


def test_a_clean_twin_that_still_names_the_dead_spouse_fails_the_build() -> None:
    twin, spec = script("twin"), expected()["twin"]
    hh = twin.household
    account, name, person = spec["stale"]
    stale = Beneficiary(account, "contingent", name, "spouse", D(100), person, hh.configured)
    named = dataclasses.replace(twin, household=dataclasses.replace(hh, beneficiaries=(*hh.beneficiaries, stale)))
    with pytest.raises(PlantError, match=spec["refusal"]):
        plant(context(named))


def test_without_its_entry_the_unbooked_step_up_fails_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reviewer A, slice 5 round 1: the CRM's death notification is now compared with the custodian.
    import casebook.build
    from casebook.build import BuildError
    from casebook.plant import Planting

    trap = expected()["trap"]
    real_plant = casebook.build.plant

    def without_entry(context: PlantContext) -> Planting:
        planting = real_plant(context)
        if context.script.household.household_id == trap["household_id"]:
            return Planting(entries=(), custodian_events=planting.custodian_events)
        return planting

    monkeypatch.setattr(casebook.build, "plant", without_entry)
    with pytest.raises(BuildError, match=f"booked no step-up on {trap['joint_account']}"):
        build_book(SEED, tmp_path / "book", PAIR, held_out=True)
