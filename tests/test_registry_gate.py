"""Slice 4: every planted item has a registry entry, and an unregistered difference fails the build."""

import dataclasses
import json
import tomllib
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import casebook.build
import casebook.sources.documents
from casebook.build import BuildError, build_book
from casebook.model.files import json_text
from casebook.plant import PlantContext, Planting
from casebook.sources.context import EmitContext
from casebook.sources.transactions import TransactionRow

from .conftest import FEATURED, SCRIPTS, SEED, held_out_featured

REQUIRED = ("item_id", "type", "sources", "justified_conclusion")


def test_every_planted_item_has_a_registry_entry_with_id_type_sources_and_conclusion(book: Path) -> None:
    scripts = {p: tomllib.loads(p.read_text()) for p in sorted(SCRIPTS.rglob("*.toml"))}
    planted = {raw["planted"]["item_id"] for raw in scripts.values() if "planted" in raw}
    held = {
        raw["planted"]["item_id"]
        for raw in scripts.values()
        if "planted" in raw and raw.get("household_id") in held_out_featured()
    }
    entries = {e["item_id"]: e for e in json.loads((book / "sealed" / "registry.json").read_text())["entries"]}
    # One per public trap: archetypes 1 to 6, 9 and 10; and 7 and 8 once the freeze moves them in.
    assert planted - held == {"PI-0001", "PI-0002", "PI-0003", "PI-0004", "PI-0005", "PI-0006", "PI-0007", "PI-0010"}
    assert len(held) == len(held_out_featured()) // 2
    assert planted <= set(entries)
    for item_id in planted:
        entry = entries[item_id]
        assert all(entry[field] for field in REQUIRED), entry
        assert entry["household_id"] in FEATURED and entry["kind"] in ("situation", "source_disagreement")
    # The fee breakpoint's difference lies between the CRM's signed letter and the portfolio system's groups.
    assert {"crm/crm.json", "portfolio/household.json"} <= set(entries["PI-0001"]["sources"])


def test_a_build_with_an_unregistered_difference_between_two_sources_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The portfolio system loses one cash line for the twin's IRA, while the custodian keeps it, and
    # nothing registers the difference. (A script cannot do this: every source is drawn from one script.)
    real_emit = casebook.build.emit_household

    def emit_with_a_difference(*args: Any, **kwargs: Any) -> dict[str, bytes]:
        files = real_emit(*args, **kwargs)
        name = "households/HH-7350/portfolio/positions.json"
        if name in files:
            data = json.loads(files[name])
            data["cash"] = [c for c in data["cash"] if c["account_id"] != "SYN-73500002"]
            files[name] = json_text(data).encode()
        return files

    monkeypatch.setattr(casebook.build, "emit_household", emit_with_a_difference)
    with pytest.raises(BuildError, match=r"two sources disagree with no registry entry .*SYN-73500002 cash"):
        build_book(SEED, tmp_path / "book", SCRIPTS)
    assert not (tmp_path / "book").exists(), "a refused build leaves no book behind"


def test_a_statement_whose_activity_differs_from_the_custodian_fails_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # B-S2, slice 4 round 1: the twin's statements print every fee as 1.00 while the custodian
    # keeps the real debits.
    real_rows = casebook.sources.documents.transaction_rows

    def rows_with_wrong_fees(context: EmitContext) -> list[TransactionRow]:
        rows = real_rows(context)
        if context.script.household.household_id != "HH-7350":
            return rows
        return [dataclasses.replace(r, amount=Decimal("-1.00")) if r.kind == "FEE" else r for r in rows]

    monkeypatch.setattr(casebook.sources.documents, "transaction_rows", rows_with_wrong_fees)
    with pytest.raises(BuildError, match=r"statement-SYN-7350000\d-2026Q1\.pdf and custodian/transactions\.csv"):
        build_book(SEED, tmp_path / "book", SCRIPTS)


def test_a_statement_that_repeats_an_activity_row_fails_the_build_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reviewers A and B, slice 4 round 2: a repeated row made the lists differ with no row to name,
    # and the check crashed.
    real_rows = casebook.sources.documents.transaction_rows

    def rows_with_a_repeat(context: EmitContext) -> list[TransactionRow]:
        rows = real_rows(context)
        if context.script.household.household_id != "HH-7350":
            return rows
        fee = next(r for r in rows if r.kind == "FEE" and r.trade_date.isoformat() == "2026-01-02")
        return [*rows, fee]

    monkeypatch.setattr(casebook.sources.documents, "transaction_rows", rows_with_a_repeat)
    with pytest.raises(
        BuildError, match=r"activity from 2026-01-01 to 2026-03-31 differs, first at 2026-01-02 Advisory fee"
    ):
        build_book(SEED, tmp_path / "book", SCRIPTS)
    assert not (tmp_path / "book").exists()


def test_a_build_whose_check_breaks_leaves_no_book_behind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(root: Path) -> list[str]:
        raise RuntimeError("the check broke")

    monkeypatch.setattr(casebook.build, "check_sources_agree", broken)
    with pytest.raises(RuntimeError, match="the check broke"):
        build_book(SEED, tmp_path / "book", SCRIPTS)
    assert not (tmp_path / "book").exists()


@pytest.mark.parametrize(
    ("household", "difference"),
    [
        # Reviewer A, slice 5 round 1: removing the RSU item's entry let the custodian's missing basis through.
        (
            "HH-3058",
            r"crm/crm\.json and custodian/transactions\.csv disagree .*"
            r"CA-3058-01 releases 800 units on 2025-02-20 at 216\.06; the custodian's vesting shows no basis",
        ),
        (
            "HH-6047",
            r"CA-6047-02: a charity received 12000\.00 from SYN-60470002 on 2025-09-15; "
            r"the custodian shows DISTRIBUTION",
        ),
    ],
)
def test_a_crm_record_the_custodian_contradicts_fails_the_build_without_its_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, household: str, difference: str
) -> None:
    real_plant = casebook.build.plant

    def without_entry(context: PlantContext) -> Planting:
        planting = real_plant(context)
        if context.script.household.household_id == household:
            return Planting(entries=(), custodian_events=planting.custodian_events)
        return planting

    monkeypatch.setattr(casebook.build, "plant", without_entry)
    with pytest.raises(BuildError, match=difference):
        build_book(SEED, tmp_path / "book", SCRIPTS)
