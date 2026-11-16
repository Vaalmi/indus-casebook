import json
from pathlib import Path

import pytest

from casebook.checks import CHECKS, check_book
from casebook.cli import main

HH = "HH-4821"


def household(book: Path) -> Path:
    return book / "households" / HH


def edit_csv_cell(path: Path, match: dict[str, str], column: str, value: str) -> int:
    """Change one cell in the first row matching `match`; return the row's line number."""
    lines = path.read_text().splitlines()
    header = lines[0].split(",")
    for number, line in enumerate(lines[1:], start=2):
        cells = line.split(",")
        if all(cells[header.index(k)] == v for k, v in match.items()):
            cells[header.index(column)] = value
            lines[number - 1] = ",".join(cells)
            path.write_text("\n".join(lines) + "\n")
            return number
    raise AssertionError(f"no row matches {match}")


def failures(book: Path) -> dict[tuple[str, str], tuple[str, ...]]:
    return {(line.household_id, line.check): line.problems for line in check_book(book).lines if not line.passed}


def test_the_built_book_passes_every_check_on_every_household(book: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report = check_book(book)
    assert report.passed
    assert [(line.household_id, line.check) for line in report.lines] == [
        (h, c) for h in ("HH-4821", "HH-7350") for c in CHECKS
    ]
    assert main(["check", "--book", str(book)]) == 0
    assert capsys.readouterr().out.endswith("6 lines: 6 pass, 0 fail\n")


def test_a_unit_defect_fails_the_units_check_and_names_file_line_and_account(book_copy: Path) -> None:
    path = household(book_copy) / "custodian" / "positions.csv"
    line = edit_csv_cell(
        path, {"account_id": "SYN-48210001", "security_id": "SEC-0001", "valuation_date": "2025-06-30"}, "units", "1"
    )
    problems = failures(book_copy)[(HH, "units")]
    assert any(f"custodian/positions.csv line {line}: SYN-48210001 SEC-0001 on 2025-06-30" in p for p in problems)
    assert set(failures(book_copy)) == {(HH, "units")}


def test_open_lots_that_disagree_with_closing_units_fail_the_units_check(book_copy: Path) -> None:
    path = household(book_copy) / "custodian" / "tax_lots.csv"
    edit_csv_cell(path, {"lot_id": "L-48210003-02"}, "units", "1")
    problems = failures(book_copy)[(HH, "units")]
    assert any("custodian/tax_lots.csv: SYN-48210003 SEC-0005 open lots hold" in p for p in problems)


def test_a_cash_defect_fails_the_cash_check_and_names_file_line_and_account(book_copy: Path) -> None:
    path = household(book_copy) / "custodian" / "cash.csv"
    line = edit_csv_cell(path, {"account_id": "SYN-48210002", "valuation_date": "2025-09-30"}, "settled_cash", "1.00")
    problems = failures(book_copy)[(HH, "cash")]
    assert any(
        f"custodian/cash.csv line {line}: SYN-48210002 settled cash on 2025-09-30 is 1.00" in p for p in problems
    )


def test_a_valuation_date_after_its_known_as_of_date_fails_the_dates_check(book_copy: Path) -> None:
    path = household(book_copy) / "crm" / "crm.json"
    crm = json.loads(path.read_text())
    crm["notes"][0]["known_as_of"] = "2016-01-01"
    path.write_text(json.dumps(crm))
    problems = failures(book_copy)[(HH, "valuation date not after known-as-of")]
    assert problems == ("crm/crm.json.notes[0]: valuation_date 2016-04-12 is later than known_as_of 2016-01-01",)


def test_a_csv_row_dated_after_it_was_known_fails_the_dates_check(book_copy: Path) -> None:
    path = household(book_copy) / "custodian" / "transactions.csv"
    line = edit_csv_cell(path, {"transaction_id": "T-4821-0004"}, "known_as_of", "2025-02-17")
    problems = failures(book_copy)[(HH, "valuation date not after known-as-of")]
    assert problems == (
        f"custodian/transactions.csv line {line}: valuation_date 2025-02-18 is later than known_as_of 2025-02-17",
    )


def test_a_missing_file_fails_with_its_name(book_copy: Path) -> None:
    (household(book_copy) / "custodian" / "cash.csv").unlink()
    assert failures(book_copy)[(HH, "cash")] == ("custodian/cash.csv: missing",)


def test_the_check_command_exits_non_zero_on_a_fail(book_copy: Path, capsys: pytest.CaptureFixture[str]) -> None:
    edit_csv_cell(household(book_copy) / "custodian" / "cash.csv", {"account_id": "SYN-48210001"}, "settled_cash", "0")
    assert main(["check", "--book", str(book_copy)]) == 1
    out = capsys.readouterr().out
    assert f"{HH}  cash" in out and "FAIL" in out


def keep_rows(path: Path, valuation_date: str) -> None:
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], *(line for line in lines[1:] if f",{valuation_date}," in line)]) + "\n")


def test_cash_with_no_opening_balance_fails(book_copy: Path) -> None:
    # Reviewer B, slice 1 round 1, S2: closing rows alone gave nothing to compare and passed.
    path = household(book_copy) / "custodian" / "cash.csv"
    keep_rows(path, "2026-04-15")
    edit_csv_cell(path, {"account_id": "SYN-48210001"}, "settled_cash", "1.00")
    problems = failures(book_copy)[(HH, "cash")]
    assert problems == (
        "custodian/cash.csv: needs the opening balance on 2024-12-31 and the closing balance on 2026-04-15; "
        "it has 2026-04-15",
    )


def test_positions_with_no_opening_positions_fail(book_copy: Path) -> None:
    keep_rows(household(book_copy) / "custodian" / "positions.csv", "2026-04-15")
    problems = failures(book_copy)[(HH, "units")]
    assert problems[0].startswith("custodian/positions.csv: needs the opening positions on 2024-12-31")


def test_an_account_missing_from_a_cash_balance_fails(book_copy: Path) -> None:
    path = household(book_copy) / "custodian" / "cash.csv"
    lines = path.read_text().splitlines()
    path.write_text(
        "\n".join(line for line in lines if not line.startswith("SYN-48210003,") or "2025-06-30" not in line) + "\n"
    )
    problems = failures(book_copy)[(HH, "cash")]
    assert "custodian/cash.csv: account SYN-48210003 has no balance on 2025-06-30" in problems
