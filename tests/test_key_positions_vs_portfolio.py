"""The positions-against-portfolio key (T-REC-06) against a hand-built book and the built one, and key
mutations the household list grader catches."""

import dataclasses
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.household_list import grade
from casebook.keys.figures import KeyFigure
from casebook.keys.positions_vs_portfolio import Difference, PositionsKey, positions_key
from casebook.model.files import (
    CASH_COLUMNS,
    CASH_CSV,
    MANIFEST,
    PORTFOLIO_POSITIONS,
    POSITIONS_COLUMNS,
    POSITIONS_CSV,
    csv_text,
    household_dir,
    json_text,
)
from casebook.tasks.fixtures import load_task_fixtures
from casebook.tasks.task import BOOK

AS_OF = date(2026, 4, 15)
DAY = "2026-04-15"
A, B = "SYN-00010001", "SYN-00010002"

# Account A holds 100 units at 50.00 (5,000.00) and 1,000.00 cash (900.00 settled, 100.00 unsettled);
# account B holds 10 units at 20.00 (200.00) and 0.00 cash. Each case below changes one line of it.
HOLDINGS = [(A, "SEC-0001", "100", "50.00", "5000.00"), (B, "SEC-0002", "10", "20.00", "200.00")]
CASH = [(A, "900.00", "100.00"), (B, "0.00", "0.00")]


def _custodian(holdings: list[tuple[str, ...]], cash: list[tuple[str, ...]], day: str = DAY) -> dict[str, str]:
    return {
        POSITIONS_CSV: csv_text(
            POSITIONS_COLUMNS,
            [
                {
                    "account_id": account,
                    "security_id": security,
                    "security": security,
                    "units": units,
                    "price": price,
                    "price_label": "synthetic",
                    "market_value": value,
                    "valuation_date": day,
                    "known_as_of": known,
                }
                for account, security, units, price, value, known in ((*h, day) if len(h) == 5 else h for h in holdings)
            ],
        ),
        CASH_CSV: csv_text(
            CASH_COLUMNS,
            [
                {
                    "account_id": account,
                    "settled_cash": settled,
                    "unsettled_cash": unsettled,
                    "valuation_date": day,
                    "known_as_of": day,
                }
                for account, settled, unsettled in cash
            ],
        ),
    }


def _portfolio(holdings: list[tuple[str, ...]], cash: list[tuple[str, str]], day: str = DAY) -> dict[str, str]:
    positions: list[dict[str, Any]] = [
        {
            "account_id": account,
            "security_id": security,
            "units": units,
            "price": price,
            "market_value": value,
            "valuation_date": day,
            "known_as_of": day,
        }
        for account, security, units, price, value in holdings
    ]
    lines = [{"account_id": a, "cash": c, "valuation_date": day, "known_as_of": day} for a, c in cash]
    return {PORTFOLIO_POSITIONS: json_text({"positions": positions, "cash": lines})}


PORTFOLIO_CASH = [(A, "1000.00"), (B, "0.00")]


def _write(book: Path, household: str, files: dict[str, str]) -> None:
    root = book / household_dir(household)
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")


@pytest.fixture
def hand_book(tmp_path: Path) -> Path:
    book = tmp_path / "book"
    cases = {
        # The two sources agree; a custodian line known only after the as-of date is not on file yet.
        "HH-0001": {
            **_custodian([*HOLDINGS, (B, "SEC-0003", "5", "10.00", "50.00", "2026-04-16")], CASH),
            **_portfolio(HOLDINGS, PORTFOLIO_CASH),
        },
        # A's units differ (100 against 90), and B's cash (0.00 against 25.00).
        "HH-0002": {
            **_custodian(HOLDINGS, CASH),
            **_portfolio([(A, "SEC-0001", "90", "50.00", "4500.00"), HOLDINGS[1]], [(A, "1000.00"), (B, "25.00")]),
        },
        # The portfolio system holds a security in B the custodian does not.
        "HH-0003": {
            **_custodian(HOLDINGS, CASH),
            **_portfolio([*HOLDINGS, (B, "SEC-0004", "1", "1.00", "1.00")], PORTFOLIO_CASH),
        },
        # The portfolio system states nothing valued on 15 April 2026: nothing to compare.
        "HH-0004": {**_custodian(HOLDINGS, CASH), **_portfolio(HOLDINGS, PORTFOLIO_CASH, day="2026-04-14")},
    }
    for household, files in cases.items():
        _write(book, household, files)
    manifest = {
        "version": "0.0.1",
        "seed": 1,
        "households": [{"household_id": h, "archetype": 1, "state": "ok"} for h in cases],
        "files": {},
    }
    (book / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    return book


def _figures(key: PositionsKey, household: str) -> dict[str, Decimal]:
    return {f.label: f.value for h in key.household_figures if h.household_id == household for f in h.figures}


def test_a_household_whose_sources_differ_is_found_with_the_accounts_that_differ(hand_book: Path) -> None:
    key = positions_key(hand_book, AS_OF)
    assert key.checked == ("HH-0001", "HH-0002", "HH-0003", "HH-0004")
    assert dict(key.found) == {"HH-0002": (A, B), "HH-0003": (B,)}
    assert key.unresolved == ("HH-0004",)
    differences = dict(key.differences)
    assert differences["HH-0002"] == (
        Difference(
            A,
            "SEC-0001",
            (Decimal(100), Decimal("50.00"), Decimal("5000.00")),
            (Decimal(90), Decimal("50.00"), Decimal("4500.00")),
        ),
        Difference(B, "cash", (Decimal("0.00"),), (Decimal("25.00"),)),
    )
    assert differences["HH-0003"] == (Difference(B, "SEC-0004", None, (Decimal(1), Decimal("1.00"), Decimal("1.00"))),)


def test_the_figures_add_up_each_source(hand_book: Path) -> None:
    key = positions_key(hand_book, AS_OF)
    agreeing = _figures(key, "HH-0001")
    # Custodian: 5,000.00 + 200.00 of positions and 900.00 + 100.00 + 0.00 of cash: 6,200.00. The late line
    # (50.00) is not counted.
    assert agreeing["custodian SYN-00010001 cash"] == Decimal("1000.00")
    assert agreeing["custodian total value"] == Decimal("6200.00")
    assert agreeing["portfolio system total value"] == Decimal("6200.00")
    differing = _figures(key, "HH-0002")
    # 100 - 90 units, 5,000.00 - 4,500.00 of value, 0.00 - 25.00 of cash; the portfolio system's total is
    # 4,500.00 + 200.00 + 1,000.00 + 25.00 = 5,725.00.
    assert differing[f"{A} SEC-0001 units difference"] == Decimal(10)
    assert differing[f"{A} SEC-0001 value difference"] == Decimal("500.00")
    assert differing[f"{B} cash difference"] == Decimal("-25.00")
    assert differing["portfolio system total value"] == Decimal("5725.00")
    assert _figures(key, "HH-0004") == {}


def test_the_key_writes_as_json_with_money_as_strings(hand_book: Path) -> None:
    data = positions_key(hand_book, AS_OF).to_dict()
    assert data["found"] == {"HH-0002": [A, B], "HH-0003": [B]}
    assert data["unresolved"] == ["HH-0004"]
    assert data["differences"]["HH-0003"][0] == {
        "account_id": B,
        "item": "SEC-0004",
        "custodian": None,
        "portfolio": ["1", "1.00", "1.00"],
    }
    json.dumps(data)


def test_no_household_in_the_whole_book_disagrees_on_the_scenario_date(full_book: Path) -> None:
    # The book plants no positions or cash disagreement on 15 April 2026 (sealed/registry.json): a clean book.
    key = positions_key(full_book, AS_OF)
    assert len(key.checked) == 88
    assert (dict(key.found), key.unresolved) == ({}, ())


def test_the_trap_household_totals_are_the_files_added_up(book: Path) -> None:
    figures = _figures(positions_key(book, AS_OF), "HH-4821")
    # Worked by hand from custodian/positions.csv and cash.csv on 2026-04-15. Positions: the joint account
    # 328,049.04 + 138,623.94 + 231,453.44 + 169,025.82 = 867,152.24; Henrik's IRA 219,525.68 + 212,419.44
    # = 431,945.12; Ngozi's account 269,931.20 + 164,073.08 + 140,131.53 = 574,135.81; in all 1,873,233.17.
    # Cash 25,908.62 + 3,710.13 + 10,010.55 = 39,629.30. Total 1,912,862.47, the same in both sources.
    assert figures["custodian SYN-48210001 positions value"] == Decimal("867152.24")
    assert figures["custodian positions value"] == Decimal("1873233.17")
    assert figures["custodian cash"] == Decimal("39629.30")
    assert figures["custodian total value"] == figures["portfolio system total value"] == Decimal("1912862.47")


def test_the_key_gives_the_same_answer_on_the_real_ticker_build(book: Path, real_book: Path) -> None:
    assert positions_key(real_book, AS_OF).to_dict() == positions_key(book, AS_OF).to_dict()


# Key mutations: a clean answer that passes against the key fails once the key is altered.

CLEAN = {
    "finding": "none_found",
    "households": [],
    "unresolved": [],
    "figures": [
        {
            "label": "HH-4821 custodian total value on 2026-04-15",
            "value": "1,912,862.47",
            "source": "households/HH-4821/custodian/positions.csv",
            "computed": True,
        }
    ],
    "explanation": "Every household's custodian positions and cash match the portfolio system on 15 April 2026.",
}


@pytest.fixture(scope="module")
def workspace(book: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("rec06")
    load_task_fixtures(book, BOOK, ("custodian", "portfolio"), AS_OF, folder)
    return folder


def _answer() -> str:
    return f"No household disagrees.\n\n```json\n{json.dumps(CLEAN, indent=2)}\n```\n"


def test_the_clean_answer_passes_against_the_key(book: Path, workspace: Path) -> None:
    result = grade(_answer(), positions_key(book, AS_OF), workspace)
    assert (result.score, result.critical_fail, result.passed) == (100, None, True)


def test_a_key_that_finds_a_household_fails_the_clean_answer(book: Path, workspace: Path) -> None:
    key = positions_key(book, AS_OF)
    altered = Difference("SYN-48210001", "cash", (Decimal("25908.62"),), (Decimal("25000.00"),))
    result = grade(_answer(), dataclasses.replace(key, differences=(("HH-4821", (altered,)),)), workspace)
    assert next(c for c in result.breakdown if c.name == "none_missed").earned == 0
    assert not result.passed


def test_a_key_that_leaves_a_household_unresolved_fails_the_clean_answer(book: Path, workspace: Path) -> None:
    key = dataclasses.replace(positions_key(book, AS_OF), unresolved=("HH-4821",))
    result = grade(_answer(), key, workspace)
    assert not result.passed


def test_an_altered_figure_fails_the_clean_answer_as_fabricated(book: Path, workspace: Path) -> None:
    key = positions_key(book, AS_OF)
    figures = tuple(
        dataclasses.replace(
            h,
            figures=tuple(
                KeyFigure(f.label, f.value + 100) if f.value == Decimal("1912862.47") else f for f in h.figures
            ),
        )
        for h in key.household_figures
    )
    result = grade(_answer(), dataclasses.replace(key, household_figures=figures), workspace)
    assert result.critical_fail is not None and "1912862.47" in result.critical_fail
    assert (result.score, result.passed) == (0, False)
