"""The audit log's check (docs/PLAN.md, slice 12): it shows each line checked and each defect, and zero
arithmetic defects open, or it names what is missing."""

import csv
from pathlib import Path

import pytest

from casebook.checks.audit_log import audit_log_problems
from casebook.checks.audit_sheet import COLUMNS, write_audit_sheet
from casebook.model.files import csv_text
from casebook.seeding import derive_rng


@pytest.fixture(scope="module")
def worksheet(full_book: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_audit_sheet(full_book, tmp_path_factory.mktemp("audit"), derive_rng("audit", 2026))[0]


def filled(worksheet: Path) -> list[dict[str, str]]:
    """The worksheet as an owner who found nothing wrong fills it."""
    with worksheet.open() as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row.update(checked="yes", result="ok")
    return rows


def write(path: Path, rows: list[dict[str, str]]) -> Path:
    path.write_text(csv_text(COLUMNS, rows))
    return path


def test_a_complete_log_with_no_open_defect_passes(worksheet: Path, tmp_path: Path) -> None:
    rows = filled(worksheet)
    rows[3].update(result="defect", note="value off by a cent", fixed_in="0.0.2")
    assert audit_log_problems(write(tmp_path / "log.csv", rows), worksheet) == []


def test_a_figure_altered_in_the_log_fails(worksheet: Path, tmp_path: Path) -> None:
    rows = filled(worksheet)
    rows[0]["figures"] = rows[0]["figures"].replace("[", "0 [", 1)
    rows[1]["stated_result"] = "1.00 [custodian/positions.csv line 3]"
    where = [f"{r['household_id']} line {r['line']}" for r in rows[:2]]
    assert audit_log_problems(write(tmp_path / "log.csv", rows), worksheet) == [
        f"{where[0]}: figures changed from the worksheet",
        f"{where[1]}: stated_result changed from the worksheet",
    ]


def test_an_unchecked_line_fails(worksheet: Path, tmp_path: Path) -> None:
    rows = filled(worksheet)
    rows[5].update(checked="no")
    rows[6].update(checked="", result="")
    where = [f"{r['household_id']} line {r['line']}" for r in rows[5:7]]
    assert audit_log_problems(write(tmp_path / "log.csv", rows), worksheet) == [
        f"{where[0]}: not checked",
        f"{where[1]}: not checked",
        f"{where[1]}: result is '', not ok or defect",
    ]


def test_an_open_defect_fails(worksheet: Path, tmp_path: Path) -> None:
    rows = filled(worksheet)
    rows[2].update(result="defect", note="the gain is a dollar short")
    where = f"{rows[2]['household_id']} line {rows[2]['line']}"
    assert audit_log_problems(write(tmp_path / "log.csv", rows), worksheet) == [
        f"{where}: an arithmetic defect still open"
    ]


def test_a_defect_with_no_note_fails(worksheet: Path, tmp_path: Path) -> None:
    rows = filled(worksheet)
    rows[2].update(result="defect", fixed_in="0.0.2")
    where = f"{rows[2]['household_id']} line {rows[2]['line']}"
    assert audit_log_problems(write(tmp_path / "log.csv", rows), worksheet) == [f"{where}: a defect with no note"]


def test_a_missing_line_fails(worksheet: Path, tmp_path: Path) -> None:
    rows = filled(worksheet)
    gone = rows.pop(10)
    assert audit_log_problems(write(tmp_path / "log.csv", rows), worksheet) == [
        f"{gone['household_id']} line {gone['line']}: missing from the log"
    ]


def test_a_log_in_another_format_fails(worksheet: Path, tmp_path: Path) -> None:
    log = tmp_path / "log.csv"
    log.write_text("household_id,line,checked\n")
    assert audit_log_problems(log, worksheet)[0].startswith("log.csv: columns")


def test_a_line_twice_in_the_log_fails(worksheet: Path, tmp_path: Path) -> None:
    rows = filled(worksheet)
    rows.append(dict(rows[4]))
    assert audit_log_problems(write(tmp_path / "log.csv", rows), worksheet) == [
        f"{rows[4]['household_id']} line {rows[4]['line']}: in the log 2 times"
    ]


@pytest.mark.parametrize("version", ["0.0.1", "0.0.0"])
def test_a_defect_fixed_in_the_audited_version_or_before_fails(worksheet: Path, tmp_path: Path, version: str) -> None:
    """Reviewers A and B, slice 12 round 1 (a note): any fix ships as a new book version."""
    assert worksheet.parent.name == "0.0.1"
    rows = filled(worksheet)
    rows[2].update(result="defect", note="the gain is a dollar short", fixed_in=version)
    where = f"{rows[2]['household_id']} line {rows[2]['line']}"
    assert audit_log_problems(write(tmp_path / "log.csv", rows), worksheet) == [
        f"{where}: fixed in {version}, not a version after the audited 0.0.1"
    ]
