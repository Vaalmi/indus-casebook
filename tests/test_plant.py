"""The planted item's figures, recomputed here from the emitted files alone."""

import csv
import dataclasses
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

from casebook.generate.script import load_scripts
from casebook.generate.simulate import simulate
from casebook.model.household import Agreement, BillingGroup
from casebook.plant import PlantError, plant
from casebook.securities.market import build_market
from casebook.securities.master import load_master

from .conftest import SCRIPTS, SEED

D = Decimal
ACCOUNTS = ("SYN-48210001", "SYN-48210002", "SYN-48210003")


def by_hand_fee(value: Decimal) -> Decimal:
    annual = min(value, D(1_000_000)) * D("0.01")
    annual += max(min(value, D(2_000_000)) - D(1_000_000), D(0)) * D("0.008")
    annual += max(value - D(2_000_000), D(0)) * D("0.006")
    return (annual / 4).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def rows(path: Path) -> list[dict[str, str]]:
    with path.open() as handle:
        return list(csv.DictReader(handle))


def test_the_registry_figures_follow_from_the_source_files(book: Path) -> None:
    root = book / "households" / "HH-4821"
    positions = rows(root / "custodian" / "positions.csv")
    cash = rows(root / "custodian" / "cash.csv")
    fees = [t for t in rows(root / "custodian" / "transactions.csv") if t["type"] == "FEE"]
    entry = json.loads((book / "sealed" / "registry.json").read_text())["entries"][0]
    overbilled_total = D(0)
    for quarter_end, fee_date, *_rest, overbilled in entry["table"]["rows"]:
        value = sum((D(p["market_value"]) for p in positions if p["valuation_date"] == quarter_end), D(0))
        value += sum(
            (D(c["settled_cash"]) + D(c["unsettled_cash"]) for c in cash if c["valuation_date"] == quarter_end), D(0)
        )
        debited = -sum(
            (D(f["amount"]) for f in fees if f["trade_date"] == fee_date and f["account_id"] in ACCOUNTS), D(0)
        )
        expected = debited - by_hand_fee(value)
        assert D(overbilled.replace("$", "").replace(",", "")) == expected
        assert expected > 0
        overbilled_total += expected
    assert dict((f["label"], f["value"]) for f in entry["figures"])["Overbilled"] == f"${overbilled_total:,.2f}"


def test_a_planted_item_that_does_not_hold_fails_the_build() -> None:
    trap = load_scripts(SCRIPTS)[0]
    market = build_market(load_master(), SEED)
    one_group = (BillingGroup("BG-4821-1", "FS-STD", ACCOUNTS),)
    joined = dataclasses.replace(trap, household=dataclasses.replace(trap.household, billing_groups=one_group))
    with pytest.raises(PlantError, match="already bill as one group"):
        plant(joined, simulate(joined, market).quarters)


def test_a_near_miss_with_a_householding_agreement_fails_the_build() -> None:
    twin = load_scripts(SCRIPTS)[1]
    market = build_market(load_master(), SEED)
    letter = Agreement("AGR-7350-9", "householding", (), (), twin.household.configured, "joins all accounts")
    changed = dataclasses.replace(
        twin, household=dataclasses.replace(twin.household, agreements=(*twin.household.agreements, letter))
    )
    with pytest.raises(PlantError, match="near miss has no householding agreement"):
        plant(changed, simulate(changed, market).quarters)
