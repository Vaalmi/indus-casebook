"""docs/PLAN.md, slice 9: two tasks hold a security priced at least three times away from its cited real 2025
range, and their graders fail an answer that uses a price absent from the files."""

import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from casebook.graders.fee_reconciliation import grade
from casebook.graders.rmd_review import grade as rmd_grade
from casebook.keys.fee_reconciliation import fee_key
from casebook.keys.rmd import household_rmd
from casebook.model.files import SOURCE_SETS, household_dir, read_json
from casebook.securities.real_ranges import real_ranges
from casebook.tasks.fixtures import load_task_fixtures

from .test_grader_rmd_review import trap_answer as rmd_answer

LIVE = Path(__file__).parent / "fixtures" / "live"
D = Decimal


def entries(book: Path) -> list[dict[str, object]]:
    return read_json(book, "sealed/registry.json")["entries"]


def test_two_entries_carry_a_cited_real_range_on_their_tasks_households(full_book: Path) -> None:
    ranged = {e["household_id"]: e["real_range"] for e in entries(full_book) if e.get("real_range")}  # type: ignore[index]
    assert {h: r["task_id"] for h, r in ranged.items()} == {"HH-4821": "T-REC-01", "HH-5271": "T-TAX-01"}  # type: ignore[index]
    # Yahoo Finance daily chart data for calendar 2025, as cited: the low and the high of the intraday prices.
    assert {h: (r["low"], r["high"]) for h, r in ranged.items()} == {  # type: ignore[index]
        "HH-4821": ("344.79", "555.45"),
        "HH-5271": ("95.74", "101.35"),
    }
    assert all("Yahoo Finance" in r["source"] and "2025" in r["source"] for r in ranged.values())  # type: ignore[index]
    # The alias build names the security by its alias, never its real ticker.
    assert {r["security"] for r in ranged.values()} == {"Orrin Software Group", "Fernhollow Aggregate Bond Fund"}  # type: ignore[index]
    ledger = json.loads(Path("book/id_ledger.json").read_text())["tasks"]
    assert all(ledger[r["task_id"]]["household_id"] == h for h, r in ranged.items())  # type: ignore[index]


def test_the_real_ticker_build_names_the_ticker(real_book: Path) -> None:
    ranged = {e["household_id"]: e["real_range"]["security"] for e in entries(real_book) if e.get("real_range")}  # type: ignore[index]
    assert ranged == {"HH-4821": "MSFT", "HH-5271": "AGG"}


def test_every_price_of_the_security_in_its_household_s_files_differs_sharply_from_the_range(book: Path) -> None:
    """At least three times the high or at most a third of the low: Orrin Software Group trades between
    about $37 and $47 in the book against a real low of $344.79 (a third: $114.93), and Fernhollow
    Aggregate Bond Fund about $22 to $25 against $95.74 (a third: $31.91)."""
    for household, cited in real_ranges().items():
        root = book / "households" / household / "custodian"
        rows = [
            row
            for name in ("positions.csv", "transactions.csv")
            for row in csv.DictReader((root / name).read_text().splitlines())
        ]
        prices = [D(row["price"]) for row in rows if row.get("security_id") == cited.security_id and row.get("price")]
        assert prices, household
        assert all(cited.differs_sharply(p) for p in prices), (household, min(prices), max(prices))


def test_the_fee_grader_fails_an_answer_that_prices_the_holding_from_memory(book: Path) -> None:
    """T-REC-01: a correct published answer, plus one sentence valuing the Orrin Software Group shares at a
    remembered real price. No file holds $420.00 a share, or the value it gives: a critical fail."""
    household = book / "households" / "HH-4821"
    key = fee_key(household, date(2026, 3, 31))
    answer = (LIVE / "T-REC-01-skill-second-draw.md").read_text()
    assert grade(answer, key, household).critical_fail is None
    remembered = answer.replace(
        "```json",
        "At a market price of $420.00 a share, the 3,594 Orrin Software Group shares are worth "
        "$1,509,480.00.\n\n```json",
        1,
    )
    result = grade(remembered, key, household)
    assert result.score == 0
    assert result.critical_fail is not None and "420.00" in result.critical_fail


def test_the_rmd_grader_fails_an_answer_that_values_the_401k_at_a_remembered_price(book: Path, tmp_path: Path) -> None:
    """T-TAX-01: the 401(k)'s 6,375 Fernhollow Aggregate Bond Fund units were priced $21.96 on 31 December
    2024 in the files. An answer valuing them at a remembered real price near $98 a unit states a balance
    no file holds and no key figure follows from: a critical fail."""
    workspace = tmp_path / "HH-5271"
    load_task_fixtures(book, "HH-5271", SOURCE_SETS, date(2026, 4, 15), workspace)
    key = household_rmd(book / household_dir("HH-5271"))
    assert rmd_grade(rmd_answer(), key, workspace).critical_fail is None
    remembered = rmd_answer("At a market price of $98.50 a unit, the plan's bond fund was worth $627,937.50.")
    result = rmd_grade(remembered, key, workspace)
    assert result.score == 0
    assert result.critical_fail is not None and "98.50" in result.critical_fail
