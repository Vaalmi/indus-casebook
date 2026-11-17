"""The source disagreements key behind T-CMP-06: a clean public book, and each kind of fact found when one
source is changed by hand in a copy of a household."""

import csv
import io
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from casebook.keys.source_disagreements import household_disagreements, source_disagreements_key
from casebook.model.files import ACCOUNTS_COLUMNS, BENEFICIARIES_COLUMNS, csv_text, household_dir

from .conftest import PUBLIC_HOUSEHOLDS


def test_no_household_of_the_public_book_disagrees(full_book: Path) -> None:
    """Slice 4's build refuses an unregistered difference, and no planted item is an identifier, beneficiary or
    ownership difference: every source states each fact alike, on both builds."""
    key = source_disagreements_key(full_book)
    assert len(key.checked) == PUBLIC_HOUSEHOLDS
    assert dict(key.found) == {}
    assert key.unresolved == () and key.computed_figures == ()


def test_the_real_ticker_build_agrees(real_book: Path) -> None:
    assert dict(source_disagreements_key(real_book).found) == {}


def _json(path: Path, change: Callable[[dict[str, Any]], None]) -> None:
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def _csv(path: Path, columns: tuple[str, ...], change: Callable[[dict[str, str]], None]) -> None:
    rows = list(csv.DictReader(io.StringIO(path.read_text())))
    for row in rows:
        change(row)
    path.write_text(csv_text(columns, rows))


def _contact(person: str, field: str, value: str) -> Callable[[dict[str, Any]], None]:
    def change(crm: dict[str, Any]) -> None:
        next(c for c in crm["contacts"] if c["person_id"] == person)[field] = value

    return change


def _replace(old: str, new: str) -> Callable[[dict[str, str]], None]:
    def change(row: dict[str, str]) -> None:
        for name, value in row.items():
            row[name] = value.replace(old, new)

    return change


def _new_primary(name: str) -> Callable[[dict[str, str]], None]:
    def change(row: dict[str, str]) -> None:
        if row["designation"] == "primary":
            row.update(name=name, person_id="")

    return change


# Each case: the household, the change to one source, and the record the key must name.
CASES = {
    # The CRM's tax ID for Daniel Cole against his W-2's 000-30-5802.
    "tax ID": ("HH-3058", "crm/crm.json", _contact("P-3058-2", "tax_id", "000-30-5809"), "P-3058-2"),
    # The CRM's relationship against the portfolio system's "spouse".
    "relationship": ("HH-3058", "crm/crm.json", _contact("P-3058-2", "relationship", "partner"), "P-3058-2"),
    # The custodian's registration of the stock plan account against its Q1 statement's.
    "registration": (
        "HH-3058",
        "custodian/accounts.csv",
        _replace("Priya Raghunathan (stock plan", "Daniel Cole (stock plan"),
        "SYN-30580002",
    ),
    # The custodian's new primary beneficiary against the change the CRM recorded (CA-0642-03).
    "beneficiary change": (
        "HH-0642",
        "custodian/beneficiaries.csv",
        _replace("Imani Lindgren", "Imani Lindgren-Okoro"),
        "SYN-06420002",
    ),
    # The custodian naming a new primary where the CRM's form sent says it still names Omar Wainwright.
    "beneficiary form sent": (
        "HH-0193",
        "custodian/beneficiaries.csv",
        _new_primary("Wen Wainwright"),
        "SYN-01930002",
    ),
    # The inherited IRA's decedent born a day later than the death certificate (CA-0466-01) says.
    "death certificate": ("HH-0466", "custodian/accounts.csv", _replace("1945-03-06", "1945-03-07"), "SYN-04660002"),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_a_fact_changed_in_one_source_is_found(case: str, full_book: Path, tmp_path: Path) -> None:
    household, relative, change, record = CASES[case]
    root = tmp_path / household
    shutil.copytree(full_book / household_dir(household), root)
    path = root / relative
    if relative.endswith(".json"):
        _json(path, change)  # type: ignore[arg-type]
    else:
        columns = ACCOUNTS_COLUMNS if relative.endswith("accounts.csv") else BENEFICIARIES_COLUMNS
        _csv(path, columns, change)  # type: ignore[arg-type]
    found = household_disagreements(root)
    assert record in {d.record_id for d in found}, (case, found)


def test_a_changed_owner_is_named_by_its_account(full_book: Path, tmp_path: Path) -> None:
    root = tmp_path / "HH-3058"
    shutil.copytree(full_book / household_dir("HH-3058"), root)
    _csv(
        root / "custodian" / "accounts.csv",
        ACCOUNTS_COLUMNS,
        lambda row: row.update(owners="Daniel Cole") if row["account_id"] == "SYN-30580002" else None,
    )
    # The portfolio system, the Q1 statement and the 2025 composite 1099 all still name Priya Raghunathan.
    assert {d.record_id for d in household_disagreements(root)} == {"SYN-30580002"}
