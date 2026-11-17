"""The hand audit's worksheet (docs/PLAN.md, slice 12): the seeded draw, and each kind of line.

Each line's expected figures are read by hand from HH-4821's files in the `book` fixture, and each
result is worked by hand from them (rule 12)."""

import csv
import json
from pathlib import Path

import pytest

import casebook.model.archetypes
from casebook.checks.audit_sheet import (
    COLUMNS,
    KINDS,
    AuditDrawError,
    AuditLine,
    draw_households,
    household_lines,
    write_audit_sheet,
)
from casebook.model.archetypes import ARCHETYPES
from casebook.seeding import derive_rng

from .conftest import FEATURED, ROOT

SEED = 2026


def archetypes(book: Path) -> dict[str, int]:
    households = json.loads((book / "sealed" / "households.json").read_text())["households"]
    return {h["household_id"]: h["archetype"] for h in households}


def test_the_draw_is_seeded_and_covers_the_ten_archetypes(full_book: Path) -> None:
    drawn = draw_households(full_book, derive_rng("audit", SEED))
    assert drawn == draw_households(full_book, derive_rng("audit", SEED))
    assert drawn != draw_households(full_book, derive_rng("audit", SEED + 1))
    assert len(drawn) == len(set(drawn)) == 15
    manifest = {h["household_id"] for h in json.loads((full_book / "manifest.json").read_text())["households"]}
    assert set(drawn) <= manifest
    assert {archetypes(full_book)[h] for h in drawn} == set(ARCHETYPES)


def relabel(book: Path, household_id: str, **fields: object) -> None:
    path = book / "sealed" / "households.json"
    data = json.loads(path.read_text())
    next(h for h in data["households"] if h["household_id"] == household_id).update(fields)
    path.write_text(json.dumps(data))


def test_the_draw_refuses_a_private_pair(book_copy: Path) -> None:
    relabel(book_copy, "HH-7350", set="background", archetype=10, pair=3)
    with pytest.raises(AuditDrawError, match="HH-7350 is a private pair"):
        draw_households(book_copy, derive_rng("audit", SEED))


@pytest.mark.parametrize("frozen_now", [False, True])
def test_the_draw_is_the_audited_15_before_and_after_the_move_in(
    full_book: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, frozen_now: bool
) -> None:
    """Archetypes 7 and 8's featured pairs move in at the freeze; the draw never picks them, so it gives the 15
    households the owner's audit log covers whether or not they are in the book."""
    record = tmp_path / "freeze.json"
    if frozen_now:
        record.write_text("{}")
    monkeypatch.setattr(casebook.model.archetypes, "FREEZE_RECORD", record)
    drawn = draw_households(full_book, derive_rng("audit", SEED))
    held_out = {h for h, a in archetypes(full_book).items() if a in (7, 8) and h in FEATURED}
    assert not set(drawn) & held_out
    with (ROOT / "published" / "audit" / "audit-log.csv").open() as handle:
        audited = {row["household_id"] for row in csv.DictReader(handle)}
    assert set(drawn) == audited


def test_the_draw_refuses_a_book_without_every_archetype(book: Path) -> None:
    # The featured households alone: archetypes 7 and 8's are never drawn, so the book lacks them.
    with pytest.raises(AuditDrawError, match="no household of archetype 7, 8"):
        draw_households(book, derive_rng("audit", SEED))


def test_the_worksheet_is_one_csv_and_a_page_per_household(full_book: Path, tmp_path: Path) -> None:
    written = write_audit_sheet(full_book, tmp_path, derive_rng("audit", SEED))
    drawn = sorted(draw_households(full_book, derive_rng("audit", SEED)))
    assert written == [tmp_path / "0.0.1" / "worksheet.csv", *(tmp_path / "0.0.1" / f"{h}.md" for h in drawn)]
    with written[0].open() as handle:
        reader = csv.DictReader(handle)
        assert tuple(reader.fieldnames or ()) == COLUMNS
        rows = list(reader)
    assert sorted({r["household_id"] for r in rows}) == drawn
    assert {r["kind"] for r in rows} <= set(KINDS)
    assert all(r[c] == "" for r in rows for c in ("checked", "result", "note", "fixed_in"))
    first = next(r for r in rows if r["household_id"] == drawn[0])
    assert first["line"] == "1"
    assert first["archetype"] == str(archetypes(full_book)[drawn[0]])
    page = written[1].read_text()
    assert page.startswith(f"# Hand audit worksheet: {drawn[0]}")
    assert f"## 1. {first['kind']}" in page


@pytest.fixture(scope="module")
def hh4821(book: Path) -> list[AuditLine]:
    return household_lines(book / "households" / "HH-4821")


def line(lines: list[AuditLine], kind: str, starts: str) -> AuditLine:
    found = [x for x in lines if x.kind == kind and x.statement.startswith(starts)]
    assert len(found) == 1, [x.statement for x in found]
    return found[0]


def values(found: AuditLine) -> list[str]:
    return [f.value for f in found.figures]


def test_a_position_value(hh4821: list[AuditLine]) -> None:
    found = line(hh4821, "position value", "SYN-48210001 SEC-0001 on 2024-12-31:")
    assert values(found) == ["1131", "265.21"]
    assert found.figures[0].source == "custodian/positions.csv line 2"
    assert "securities/prices_synthetic.csv line" in found.figures[1].source
    # 1131 x 265.21 = 299,952.51
    assert [f.value for f in found.stated] == ["299952.51"]
    portfolio = line(hh4821, "position value", "SYN-48210001 SEC-0001 on 2026-04-15 (portfolio system)")
    # 1191 x 275.44 = 328,049.04
    assert (values(portfolio), portfolio.stated[0].value) == (["1191", "275.44"], "328049.04")


def test_a_trade_and_a_dividend(hh4821: list[AuditLine]) -> None:
    trade = line(hh4821, "trade value", "BUY T-4821-0004")
    # 30 x 195.46 = 5,863.80, paid out
    assert (values(trade), trade.stated[0].value) == (["30", "195.46"], "-5863.80")
    dividend = line(hh4821, "dividend", "T-4821-0005")
    # 637 x 1.1931 = 760.0047, 760.00 to the cent
    assert (values(dividend), dividend.stated[0].value) == (["637", "1.1931"], "760.00")


def test_units_roll_forward_from_the_opening_lots(hh4821: list[AuditLine]) -> None:
    found = line(hh4821, "units roll-forward", "SYN-48210001 SEC-0001 ")
    assert [f.name for f in found.figures] == ["opening lot L-48210001-01", "BUY T-4821-0016 on 2025-05-14"]
    # 1131 + 60 = 1191
    assert (values(found), found.stated[0].value) == (["1131", "60"], "1191")
    sold = line(hh4821, "units roll-forward", "SYN-48210001 SEC-0004 ")
    assert "-150" in values(sold)


def test_cash_rolls_forward_each_quarter(hh4821: list[AuditLine]) -> None:
    found = line(hh4821, "cash roll-forward", "SYN-48210001 settled cash from 2024-12-31 to 2025-03-31")
    # 30,000.00 + 760.00 + 262.47 + 630.12 = 31,652.59
    assert values(found) == ["30000.00", "760.00", "262.47", "630.12"]
    assert found.stated[0].value == "31652.59"
    assert len([x for x in hh4821 if x.kind == "cash roll-forward"]) == 3 * 6


def test_a_realized_lot(hh4821: list[AuditLine]) -> None:
    found = line(hh4821, "realized lot", "lot L-48210001-04")
    assert values(found) == ["150", "6364.50", "2130.66", "2019-02-04", "2025-09-08"]
    # 6,364.50 - 2,130.66 = 4,233.84
    assert found.stated[0].value == "4233.84"


def test_a_quarterly_fee(hh4821: list[AuditLine]) -> None:
    found = line(hh4821, "quarterly fee", "billing group BG-4821-1 (SYN-48210001, SYN-48210002), quarter to 2025-03-31")
    assert "under AGR-4821-1 on schedule FS-STD" in found.statement
    group_value = [f.value for f in found.figures if not f.name.startswith("tier")]
    assert group_value == [
        "284864.97",
        "134948.45",
        "221482.24",
        "149048.64",
        "194443.64",
        "203268.24",
        "31652.59",
        "0.00",
        "6240.89",
        "0.00",
    ]
    assert [f.value for f in found.figures if f.name.startswith("tier")] == ["0.0100", "0.0080", "0.0060"]
    # Value 1,225,949.66: 1,000,000 x 1% = 10,000.00, plus 225,949.66 x 0.8% = 1,807.59728; 11,807.59728 / 4
    # = 2,951.89932, 2,951.90 to the cent; debited 1,979.24 + 972.66 = 2,951.90.
    assert [f.value for f in found.stated] == ["1979.24", "972.66"]


def test_a_statement_against_its_holdings_and_cash(hh4821: list[AuditLine]) -> None:
    holding = line(hh4821, "statement holding value", "SYN-48210001 Larkspur Total Market Fund on 2026-03-31")
    # 1191 x 277.05 = 329,966.55
    assert (values(holding), holding.stated[0].value) == (["1191", "277.05"], "$329,966.55")
    total = line(hh4821, "statement total", "SYN-48210001 quarterly statement total on 2026-03-31")
    # 329,966.55 + 140,509.46 + 227,501.44 + 166,617.84 + 28,030.21 = 892,625.50
    assert values(total) == ["$329,966.55", "$140,509.46", "$227,501.44", "$166,617.84", "$28,030.21"]
    assert [f.value for f in total.stated] == ["$892,625.50", "$892,625.50"]
    assert total.stated[0].source == "documents/statement-SYN-48210001-2026Q1.pdf page 1"
