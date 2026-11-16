"""Archetype 6, a QCD the custodian recorded as an ordinary distribution: the pair builds clean, and the
registry's figures follow from the emitted files, worked by hand."""

import csv
import dataclasses
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from casebook.build import build_book
from casebook.checks import check_book
from casebook.generate.script import HouseholdScript, load_scripts
from casebook.generate.simulate import simulate
from casebook.model.events import RequiredDistribution
from casebook.plant import PlantContext, PlantError, plant
from casebook.replay import replay
from casebook.securities.market import build_market
from casebook.securities.master import load_master
from casebook.sources.context import SNAPSHOT_DAYS

from .conftest import SCRIPTS, SEED

D = Decimal
PAIR = SCRIPTS / "archetype-6"


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


@pytest.fixture(scope="module")
def book(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("a06") / "book"
    build_book(SEED, out, PAIR)
    return out


def test_the_pair_passes_every_check(book: Path) -> None:
    report = check_book(book)
    assert {line.household_id for line in report.lines} == {"HH-6047", "HH-6590"}
    assert report.passed, report.render()


def test_the_custodian_and_the_crm_disagree_and_the_figures_follow_from_the_files(book: Path) -> None:
    root = book / "households" / "HH-6047"
    # Bernard Lachance, born 1947-05-09, is 78 on his 2025 birthday: Uniform Lifetime factor 22.0
    # (IRS Publication 590-B, Table III). IRA SYN-60470002 held $476,514.06 on 31 December 2024, so
    # the 2025 RMD is $476,514.06 / 22.0 = $21,659.7300 -> $21,659.73. The custodian shows two 2025
    # distributions: $12,000.00 on 2025-09-15 (the QCD, coded as an RMD with $0.00 withheld) and
    # $9,659.73 on 2025-11-18. Together $21,659.73, which meets the RMD; $12,000.00 is excluded and
    # $9,659.73 is taxable. He turned 70 on 2017-05-09 and 70 and a half on 2017-11-09.
    assert balance(root, "SYN-60470002", "2024-12-31") == D("476514.06")
    paid = [
        (t["transaction_id"], t["type"], t["amount"], t["description"])
        for t in rows(root / "custodian" / "transactions.csv")
        if t["account_id"] == "SYN-60470002" and t["type"] in ("DISTRIBUTION", "QCD")
    ]
    assert paid == [
        (
            "T-6047-0016",
            "DISTRIBUTION",
            "-12000.00",
            "Required minimum distribution for 2025, $0.00 federal tax withheld",
        ),
        (
            "T-6047-0024",
            "DISTRIBUTION",
            "-9659.73",
            "Required minimum distribution for 2025, $965.97 federal tax withheld",
        ),
    ]
    crm = json.loads((root / "crm" / "crm.json").read_text())
    evidence = {a["activity_id"]: a for a in crm["activities"]}
    for activity_id in ("CA-6047-01", "CA-6047-02"):
        assert "Tessaly Harbor Literacy Alliance" in evidence[activity_id]["summary"]
        assert "$12,000.00" in evidence[activity_id]["summary"]
    sealed = json.loads((book / "sealed" / "HH-6047" / "events.json").read_text())["events"]
    assert [(e["type"], e["amount"]) for e in sealed if e["event_id"] == "E-6047-0016"] == [("qcd", "-12000.00")]
    entry = json.loads((book / "sealed" / "registry.json").read_text())["entries"][0]
    assert (entry["item_id"], entry["kind"]) == ("PI-0007", "source_disagreement")
    assert {"custodian/transactions.csv", "crm/crm.json"} <= set(entry["sources"])
    assert {f["label"]: f["value"] for f in entry["figures"]} == {
        "QCD": "$12,000.00",
        "QCD limit, 2025": "$108,000.00",
        "2025 RMD": "$21,659.73",
        "Paid toward the 2025 RMD": "$21,659.73",
        "Excluded from income": "$12,000.00",
        "Taxable IRA distributions": "$9,659.73",
    }
    assert set(entry["references"]) == {"P-6047-1", "SYN-60470002", "T-6047-0016", "CA-6047-01", "CA-6047-02"}
    assert "2017-11-09" in entry["justified_conclusion"]


def test_the_clean_twin_codes_the_qcd_as_a_qcd(book: Path) -> None:
    root = book / "households" / "HH-6590"
    # Celestine Abara, born 1947-02-17, factor 22.0: $547,413.85 / 22.0 = $24,882.4477 -> $24,882.45,
    # met by the $15,000.00 QCD and the $9,882.45 December distribution.
    assert balance(root, "SYN-65900002", "2024-12-31") == D("547413.85")
    paid = [
        (t["type"], t["amount"])
        for t in rows(root / "custodian" / "transactions.csv")
        if t["account_id"] == "SYN-65900002" and t["type"] in ("DISTRIBUTION", "QCD")
    ]
    assert paid == [("QCD", "-15000.00"), ("DISTRIBUTION", "-9882.45")]
    assert sum((-D(a) for _, a in paid), D(0)) >= D("24882.45")


def test_the_custodian_records_the_qcd_as_an_untaxed_rmd_and_nothing_else() -> None:
    trap = context(scripts()["HH-6047"])
    recorded = plant(trap).custodian_events
    assert recorded is not None
    changed = [(a, b) for a, b in zip(trap.events, recorded, strict=True) if a != b]
    assert len(changed) == 1
    assert changed[0][1] == RequiredDistribution(
        "E-6047-0016", changed[0][0].date, "SYN-60470002", D("-12000.00"), 2025, D(0)
    )


def test_a_qcd_above_the_limit_is_refused() -> None:
    trap = scripts()["HH-6047"]
    bigger = tuple(dataclasses.replace(a, amount=D("120000.00")) if a.kind == "qcd" else a for a in trap.activity)
    with pytest.raises(PlantError, match=re.escape("above the $108,000.00 limit")):
        plant(context(dataclasses.replace(trap, activity=bigger)))


def test_a_qcd_with_no_acknowledgment_in_the_crm_is_refused() -> None:
    trap = scripts()["HH-6047"]
    hh = trap.household
    kept = tuple(a for a in hh.crm_activities if a.kind != "charity_acknowledgment")
    changed = dataclasses.replace(trap, household=dataclasses.replace(hh, crm_activities=kept))
    with pytest.raises(PlantError, match="no charity acknowledgment for"):
        plant(context(changed))


def test_a_twin_that_misses_its_rmd_is_refused() -> None:
    twin = scripts()["HH-6590"]
    kept = tuple(a for a in twin.activity if a.kind != "rmd")
    with pytest.raises(PlantError, match=re.escape("$15,000.00 paid toward the 2025 RMD of $24,882.45")):
        plant(context(dataclasses.replace(twin, activity=kept)))
