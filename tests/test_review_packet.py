"""The review packet for the CPA or EA: ten featured returns, every tax and RMD boundary case, the mapping from inputs
to form lines, and five further household files (docs/SPEC.md, What people see; the owner's choice 4,
docs/decisions/2026-11-19-slice16-release-choices.md)."""

import csv
import io
import json
import tomllib
from pathlib import Path
from typing import Any

import pytest

from casebook.notice import NOTICE, contains_notice
from casebook.publish import review_packet as module
from casebook.publish.review_packet import (
    AUDIT_LOG,
    ReviewPacketError,
    packet_zip,
    review_packet,
    write_review_packet,
)
from casebook.publish.zips import read_zip
from tests.conftest import ROOT

MAPS = ROOT / "src" / "casebook" / "tax" / "forms" / "maps"
# Each archetype's featured trap (sealed/households.json), whose return the packet carries.
TRAPS = {
    1: "HH-1204",
    2: "HH-2316",
    3: "HH-3058",
    4: "HH-4105",
    5: "HH-5271",
    6: "HH-6047",
    7: "HH-7126",
    8: "HH-8312",
    9: "HH-9234",
    10: "HH-4821",
}
# The featured twins: a near miss or unresolved twin of a tax archetype is a boundary case; a clean twin and
# archetype 10's are not.
BOUNDARY_TWINS = {"HH-1587", "HH-2749", "HH-4633", "HH-5814", "HH-7683", "HH-9571"}
NOT_BOUNDARY = {"HH-3462", "HH-6590", "HH-8865", "HH-4821", "HH-7350"}
# The hand audit's 15 (docs/STATUS.md, slice 12).
AUDITED = {
    "HH-0190",
    "HH-0330",
    "HH-0371",
    "HH-0376",
    "HH-0410",
    "HH-0420",
    "HH-0478",
    "HH-0491",
    "HH-0562",
    "HH-0608",
    "HH-0737",
    "HH-2316",
    "HH-6590",
    "HH-9234",
    "HH-9571",
}
PRIVATE_PAIRS = {(10, 3), (4, 2), (6, 4), (9, 2)}  # docs/STATUS.md, slice 11; model.archetypes
# Seed 2026's draw, pinned so a change to the draw shows.
DRAWN = ["HH-0120", "HH-0232", "HH-0425", "HH-0782", "HH-0844"]


@pytest.fixture(scope="module")
def folder(full_book: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_review_packet(full_book, tmp_path_factory.mktemp("review"))


def _files(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def _rows(data: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8"))))


def _households(book: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads((book / "sealed" / "households.json").read_text())["households"]
    return {h["household_id"]: h for h in raw}


def test_the_packet_is_written_to_the_book_version_with_its_zip(folder: Path) -> None:
    assert folder.name == "0.0.1"
    assert packet_zip(folder) == folder.parent / "review-packet-0.0.1.zip"
    assert read_zip(packet_zip(folder).read_bytes()) == _files(folder)


def test_it_opens_with_the_notice_and_says_nothing_is_reviewed(folder: Path) -> None:
    assert (folder / "NOTICE.txt").read_text() == NOTICE + "\n"
    readme = (folder / "README.md").read_text()
    assert readme.split("\n\n")[1] == NOTICE
    assert "Nothing in this packet has been reviewed." in readme
    assert "never part of the public release" in readme
    index = json.loads((folder / "packet.json").read_text())
    assert index["notice"] == NOTICE
    assert index["reviewed"] is False


def test_ten_returns_one_per_archetype(full_book: Path, folder: Path) -> None:
    index = json.loads((folder / "packet.json").read_text())
    assert {r["archetype"]: r["household_id"] for r in index["returns"]} == TRAPS
    assert sorted(p.name for p in (folder / "returns").iterdir()) == sorted(TRAPS.values())
    for household_id in TRAPS.values():
        [unit] = (folder / "returns" / household_id).iterdir()
        assert unit.name == f"TU-{household_id[3:]}-1"
        book_pdfs = sorted((full_book / "sealed" / household_id / "returns" / unit.name).glob("*.pdf"))
        assert book_pdfs
        assert sorted(p.name for p in unit.glob("*.pdf")) == [p.name for p in book_pdfs]
        for pdf in book_pdfs:
            assert (unit / pdf.name).read_bytes() == pdf.read_bytes()


def test_each_return_has_its_tax_units_facts(folder: Path) -> None:
    facts = json.loads((folder / "returns" / "HH-1204" / "TU-1204-1" / "facts.json").read_text())
    assert facts["notice"] == NOTICE
    assert facts["facts"]["filing_status"] == "married_filing_jointly"
    assert [f["wages"] for f in facts["facts"]["filers"]] == ["212000.00", "186000.00"]
    assert facts["facts"]["iras"][0]["nondeductible_contributions"] == "7000.00"
    for household_id in TRAPS.values():
        [unit] = (folder / "returns" / household_id).iterdir()
        assert json.loads((unit / "facts.json").read_text())["facts"]["tax_unit_id"] == unit.name


def test_each_return_is_read_back_line_by_line(folder: Path) -> None:
    rows = _rows((folder / "mapping" / "returns_read_back.csv").read_bytes())
    lines = {(r["household_id"], r["file"], r["line"]): r["value"] for r in rows}
    # HH-1204's AGI, $406,332.97 in its tax summary, on Form 1040 lines 11a and 11b.
    assert lines["HH-1204", "f1040.pdf", "11a"] == "406,332.97"
    assert lines["HH-1204", "f1040.pdf", "11b"] == "406,332.97"
    assert lines["HH-1204", "f1040.pdf", "status_mfj"] == "checked"
    # Its Form 8606: the $7,000 conversion of a $7,000 nondeductible contribution.
    assert lines["HH-1204", "f8606-P-1204-2.pdf", "8"] == "7,000.00"
    for household_id in TRAPS.values():
        [unit] = (folder / "returns" / household_id).iterdir()
        for pdf in unit.glob("*.pdf"):
            assert any(r["file"] == pdf.name and r["household_id"] == household_id for r in rows), pdf


def test_the_mapping_holds_the_twelve_forms_line_to_field_maps_as_one_table(folder: Path) -> None:
    rows = _rows((folder / "mapping" / "form_lines.csv").read_bytes())
    forms = sorted(p.stem for p in MAPS.glob("*.toml"))
    assert len(forms) == 12
    assert sorted({r["form"] for r in rows}) == forms
    for form in forms:
        fields = tomllib.loads((MAPS / f"{form}.toml").read_text())["fields"]
        assert {r["line"]: r["pdf_field"] for r in rows if r["form"] == form} == fields
    [line_18] = [r for r in rows if r["form"] == "f8606" and r["line"] == "18"]
    assert line_18["form_name"] == "Form 8606"
    assert line_18["pdf_field"] == "topmostSubform[0].Page2[0].f2_06[0]"
    assert line_18["label"].startswith("18. Taxable amount.")
    assert all(r["label"] for r in rows)


def test_every_tax_and_rmd_boundary_case(full_book: Path, folder: Path) -> None:
    households = _households(full_book)
    registry = json.loads((full_book / "sealed" / "registry.json").read_text())["entries"]
    cases = json.loads((folder / "boundary" / "cases.json").read_text())["cases"]
    traps = {c["household_id"] for c in cases if c["role"] == "trap"}
    twins = {c["household_id"] for c in cases if c["role"] == "twin"}
    assert traps == {e["household_id"] for e in registry if households[e["household_id"]]["archetype"] != 10}
    assert len(traps) == 42  # 46 planted items, 4 of them archetype 10's
    assert set(TRAPS.values()) - {"HH-4821"} <= traps
    assert twins >= BOUNDARY_TWINS
    assert not (traps | twins) & NOT_BOUNDARY
    for case in cases:
        household = households[case["household_id"]]
        assert household["archetype"] in range(1, 10)
        if case["role"] == "twin":
            assert household["twin_kind"] in ("near_miss", "unresolved")
            assert case["explanation"] == household["explanation"]
            assert households[case["trap"]]["pair"] == household["pair"]
        else:
            [entry] = [e for e in registry if e["household_id"] == case["household_id"]]
            assert case["planted_item"] == entry
        summary = folder / case["tax_summary"]
        assert summary.read_bytes() == (full_book / "sealed" / case["household_id"] / "tax_summary.json").read_bytes()
    near = {h for h, e in households.items() if e["archetype"] != 10 and e["twin_kind"] in ("near_miss", "unresolved")}
    assert twins == near


def test_the_two_lines_only_in_house_code_computes(full_book: Path, folder: Path) -> None:
    rows = _rows((folder / "boundary" / "in_house_lines.csv").read_bytes())
    assert {r["household_id"] for r in rows} == set(_households(full_book))
    assert {r["line"].split(" ")[0] for r in rows} == {"carryforward_short", "carryforward_long", "ira_basis"}
    [basis] = [r for r in rows if r["household_id"] == "HH-1204" and r["line"] == "ira_basis P-1204-2"]
    assert (basis["engine"], basis["keys"], basis["agrees"]) == ("6748.00", "6748.00", "yes")


def test_the_rule_readings_are_in_the_packet_with_the_notice(folder: Path) -> None:
    readings = (folder / "boundary" / "rule_readings.md").read_text()
    assert readings == (ROOT / "book" / "review" / "rule_readings.md").read_text()
    assert readings.startswith("# Rule readings")
    assert contains_notice(readings)
    assert "Source:" in readings


def test_five_further_households_meeting_the_rules(full_book: Path, folder: Path) -> None:
    households = _households(full_book)
    index = json.loads((folder / "packet.json").read_text())
    assert index["further_households"] == DRAWN
    assert sorted(p.name for p in (folder / "households").iterdir()) == DRAWN
    for household_id in DRAWN:
        household = households[household_id]
        assert household["set"] == "background"
        assert household["archetype"] in range(1, 10)
        assert household_id not in AUDITED
        assert (household["archetype"], household["pair"]) not in PRIVATE_PAIRS
        root = full_book / "households" / household_id
        book_files = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        mine = folder / "households" / household_id
        assert {p.relative_to(mine).as_posix(): p.read_bytes() for p in mine.rglob("*") if p.is_file()} == book_files
        summary = (full_book / "sealed" / household_id / "tax_summary.json").read_bytes()
        assert (folder / "tax_summaries" / f"{household_id}.json").read_bytes() == summary
    assert {r["household_id"] for r in _rows(AUDIT_LOG.read_bytes())} == AUDITED


def test_the_draw_never_takes_an_audited_household(full_book: Path, tmp_path: Path) -> None:
    households = _households(full_book)
    tax = sorted(h for h, e in households.items() if e["set"] == "background" and e["archetype"] != 10)
    left = ["HH-0129", "HH-0168", "HH-0193", "HH-0218", "HH-0221"]
    log = tmp_path / "audit-log.csv"
    log.write_text("household_id\n" + "".join(f"{h}\n" for h in tax if h not in left))
    assert json.loads(review_packet(full_book, log)["packet.json"])["further_households"] == left


def test_a_book_holding_a_private_pair_is_refused(full_book: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "PRIVATE_PAIRS", frozenset({(1, 3)}))
    with pytest.raises(ReviewPacketError, match="private pair"):
        review_packet(full_book)


def test_the_further_households_need_the_full_book(book: Path, tmp_path: Path) -> None:
    with pytest.raises(ReviewPacketError, match="build the full book"):
        write_review_packet(book, tmp_path)


def test_a_rewrite_is_byte_identical(full_book: Path, folder: Path, tmp_path: Path) -> None:
    again = write_review_packet(full_book, tmp_path)
    assert packet_zip(again).read_bytes() == packet_zip(folder).read_bytes()


def test_a_rewrite_replaces_what_the_folder_held(full_book: Path, tmp_path: Path) -> None:
    stale = tmp_path / "0.0.1" / "stale.txt"
    stale.parent.mkdir()
    stale.write_text("left over")
    folder = write_review_packet(full_book, tmp_path)
    assert not stale.exists()
    assert set(_files(folder)) == set(read_zip(packet_zip(folder).read_bytes()))
