"""Slice 4: the four source sets in full (docs/SPEC.md, The book), checked on the emitted files."""

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from .conftest import built

HOUSEHOLDS = ("HH-4821", "HH-7350")
DATES = ("valuation_date", "known_as_of")


def header(path: Path) -> list[str]:
    with path.open(newline="") as handle:
        return next(csv.reader(handle))


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


# What each custodian file must hold, from the spec's line: "positions, transactions, tax lots,
# beneficiaries, and settled and unsettled cash as separate fields".
CUSTODIAN = {
    "positions.csv": {"account_id", "security_id", "units", "price", "market_value"},
    "transactions.csv": {"transaction_id", "account_id", "trade_date", "settle_date", "type", "amount"},
    "tax_lots.csv": {"account_id", "lot_id", "security_id", "acquired_date", "units", "cost_basis"},
    "beneficiaries.csv": {"account_id", "designation", "name", "relationship", "share_percent"},
    "cash.csv": {"account_id", "settled_cash", "unsettled_cash"},
}


@pytest.mark.parametrize("household", HOUSEHOLDS)
@pytest.mark.parametrize("name", sorted(CUSTODIAN))
def test_the_custodian_set_holds_each_kind_of_record_in_its_own_fields(book: Path, household: str, name: str) -> None:
    path = book / "households" / household / "custodian" / name
    assert CUSTODIAN[name] | set(DATES) <= set(header(path))


def test_settled_and_unsettled_cash_are_separate_numbers(book: Path) -> None:
    for household in HOUSEHOLDS:
        for row in rows(book / "households" / household / "custodian" / "cash.csv"):
            assert row["settled_cash"] and row["unsettled_cash"]


def test_beneficiaries_are_held_per_account_and_designation(book: Path) -> None:
    twin = rows(book / "households" / "HH-7350" / "custodian" / "beneficiaries.csv")
    # Kenji's IRA: Maeve primary; Aiko and his nephew, who is not a household member, contingent.
    assert [(r["designation"], r["name"], r["share_percent"], r["person_id"]) for r in twin] == [
        ("primary", "Maeve Brennan-Sato", "100", "P-7350-1"),
        ("contingent", "Aiko Sato", "50", "P-7350-3"),
        ("contingent", "Ronan Sato-Quill", "50", ""),
    ]


@pytest.mark.parametrize("household", HOUSEHOLDS)
def test_the_portfolio_set_holds_ips_targets_restrictions_the_fee_schedule_and_trade_date_positions(
    book: Path, household: str
) -> None:
    portfolio = book / "households" / household / "portfolio"
    ips = json.loads((portfolio / "ips.json").read_text())
    assert ips["targets"] and all({"asset_class", "target", "band"} <= set(t) for t in ips["targets"])
    assert isinstance(ips["restrictions"], list)
    assert all({"restriction_id", "restriction"} <= set(r) for r in ips["restrictions"])
    schedules = json.loads((portfolio / "billing.json").read_text())["fee_schedules"]
    assert schedules and all(s["tiers"] for s in schedules)
    positions = json.loads((portfolio / "positions.json").read_text())
    assert positions["positions"] and {p["basis"] for p in positions["positions"]} == {"trade date"}
    assert {c["basis"] for c in positions["cash"]} == {"trade date"}


def test_a_restriction_is_recorded_with_its_date(book: Path) -> None:
    ips = json.loads((book / "households" / "HH-7350" / "portfolio" / "ips.json").read_text())
    assert ips["restrictions"] == [
        {
            "restriction_id": "R-7350-1",
            "restriction": "No individual tobacco stocks, at Maeve's request.",
            "valuation_date": "2020-02-03",
            "known_as_of": "2020-02-03",
        }
    ]


@pytest.mark.parametrize("household", HOUSEHOLDS)
def test_the_five_relations_are_separate_fields(book: Path, household: str) -> None:
    data = json.loads((book / "households" / household / "portfolio" / "household.json").read_text())
    relations = ("household_membership", "legal_ownership", "tax_units", "billing_groups", "disclosure_permissions")
    for relation in relations:
        assert isinstance(data[relation], list) and data[relation], relation
    # Each relation keys on its own subject; none is folded into another.
    assert {"person_id"} <= set(data["household_membership"][0])
    assert {"account_id", "owner_ids"} <= set(data["legal_ownership"][0])
    assert {"tax_unit_id", "person_ids"} <= set(data["tax_units"][0])
    assert {"billing_group_id", "account_ids"} <= set(data["billing_groups"][0])
    assert {"person_id", "may_be_told_about"} <= set(data["disclosure_permissions"][0])


def observations(data: Any) -> list[dict[str, Any]]:
    """The observations in a source JSON file: every item of a top-level list, and every top-level object."""
    found: list[dict[str, Any]] = []
    for value in data.values():
        if isinstance(value, list):
            found += value
        elif isinstance(value, dict):
            found.append(value)
    return found


def source_files(book: Path) -> list[Path]:
    return sorted(p for p in (book / "households").rglob("*") if p.suffix in (".csv", ".json"))


def test_every_observation_in_every_source_set_carries_both_dates(book: Path) -> None:
    files = [*source_files(book), book / "securities" / "prices_synthetic.csv"]
    # Per household: seven custodian CSVs, five portfolio files, the CRM and the documents index.
    assert len(files) == 14 * len(built(book)) + 1
    for path in files:
        records = rows(path) if path.suffix == ".csv" else observations(json.loads(path.read_text()))
        assert records or path.name in ("beneficiaries.csv", "realized_lots.csv"), path
        for record in records:
            for field in DATES:
                assert isinstance(record.get(field), str), (path, record)
                date.fromisoformat(record[field])
