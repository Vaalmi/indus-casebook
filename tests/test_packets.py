"""Case packets: one zip per featured household, its source sets as the book has them and a separate answer sheet,
with no tax answer sheet and no held key (docs/SPEC.md, What people see; the owner's choice 3(a),
docs/decisions/2026-11-19-slice16-release-choices.md)."""

import json
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.notice import NOTICE
from casebook.publish.packets import PacketError, case_packets
from casebook.publish.zips import read_zip
from tests.conftest import FEATURED, ROOT

KEYS = ROOT / "published" / "keys"
TASKS = ROOT / "tasks" / "public"
SHARED = {"securities/securities.csv", "securities/prices_synthetic.csv", "metadata.json", "NOTICE.txt"}
ANSWER_SHEET = "answer-sheet.json"
# The 17 held public tasks (docs/STATUS.md, slice 14): each one's household's packet names it and holds no key.
HELD_ON_FEATURED = {
    "HH-1204": ["T-MTG-01"],
    "HH-1587": ["T-MTG-02"],
    "HH-2316": ["T-MTG-03"],
    "HH-2749": ["T-MTG-04"],
    "HH-3058": ["T-CMP-01"],
    "HH-3462": ["T-CMP-02"],
    "HH-4105": ["T-CMP-03"],
    "HH-4633": ["T-CMP-04"],
    "HH-5271": ["T-TAX-01"],
    "HH-5814": ["T-TAX-02"],
    "HH-6047": ["T-REC-03"],
    "HH-6590": ["T-REC-04"],
    "HH-9234": ["T-TAX-03"],
    "HH-9571": ["T-TAX-04"],
}


@pytest.fixture(scope="module")
def packets(book: Path) -> dict[str, dict[str, bytes]]:
    return {name: read_zip(data) for name, data in case_packets(book, KEYS, TASKS).items()}


def _sheet(packets: dict[str, dict[str, bytes]], household_id: str) -> dict[str, Any]:
    return json.loads(packets[f"{household_id}.zip"][ANSWER_SHEET])


def test_one_packet_per_featured_household(packets: dict[str, dict[str, bytes]]) -> None:
    assert sorted(packets) == [f"{h}.zip" for h in FEATURED]
    assert len(packets) == 20


def test_a_packet_holds_its_source_sets_as_the_book_has_them_and_nothing_else(
    book: Path, packets: dict[str, dict[str, bytes]]
) -> None:
    for household_id in FEATURED:
        root = book / "households" / household_id
        sources = {p.relative_to(book).as_posix() for p in root.rglob("*") if p.is_file()}
        files = packets[f"{household_id}.zip"]
        assert set(files) == sources | SHARED | {ANSWER_SHEET}
        assert {name.split("/")[2] for name in sources} == {"custodian", "portfolio", "crm", "documents"}
        for name in sources | (SHARED - {"NOTICE.txt"}):
            assert files[name] == (book / name).read_bytes(), name
        assert files["NOTICE.txt"] == (NOTICE + "\n").encode()


def test_no_tax_answer_sheet_return_or_event_log_in_any_packet(
    book: Path, packets: dict[str, dict[str, bytes]]
) -> None:
    for name, files in packets.items():
        assert not [f for f in files if f.startswith("sealed/") or "tax_summary" in f or "/returns/" in f], name
        household_id = name.removesuffix(".zip")
        summary = json.loads((book / "sealed" / household_id / "tax_summary.json").read_text())
        sheet = files[ANSWER_SHEET].decode()
        # The income tax is the summary's own figure. A conclusion may state an income it rests on (the NIIT trap's
        # modified AGI), as the household page does (the owner's decision on U4); never the tax.
        for unit in summary["summaries"]:
            tax = Decimal(unit["income_tax"])
            if tax > 1000:
                assert str(tax) not in sheet, name
                assert f"{tax:,}" not in sheet, name


def test_every_packet_has_an_answer_sheet_with_the_notice(packets: dict[str, dict[str, bytes]]) -> None:
    for household_id in FEATURED:
        sheet = _sheet(packets, household_id)
        assert sheet["notice"] == NOTICE
        assert sheet["household_id"] == household_id
        assert sheet["held_until_review"]["tax_summary"]


def test_a_trap_sheet_holds_its_justified_conclusion_with_its_figures(packets: dict[str, dict[str, bytes]]) -> None:
    sheet = _sheet(packets, "HH-4821")
    assert sheet["role"] == "trap"
    assert sheet["explanation"] is None
    [item] = sheet["planted_items"]
    assert item["item_id"] == "PI-0001"
    assert item["justified_conclusion"].endswith("The household was overbilled by $1,410.05.")
    assert {"label": "Overbilled", "value": "$1,410.05"} in item["figures"]
    assert item["table"]["rows"][-1][-1] == "$290.25"
    # What the household page does not show stays out: the cited real price range, the references, the dates.
    assert set(item) == {"item_id", "title", "kind", "sources", "justified_conclusion", "figures", "table"}


def test_a_tax_trap_sheet_holds_its_conclusion_as_the_page_does(
    book: Path, packets: dict[str, dict[str, bytes]]
) -> None:
    registry = json.loads((book / "sealed" / "registry.json").read_text())["entries"]
    for household_id in ("HH-5271", "HH-9234", "HH-1204"):
        [entry] = [e for e in registry if e["household_id"] == household_id]
        [item] = _sheet(packets, household_id)["planted_items"]
        assert item["justified_conclusion"] == entry["justified_conclusion"]
        assert item["figures"] == entry["figures"]


def test_a_twin_sheet_holds_its_explanation(packets: dict[str, dict[str, bytes]]) -> None:
    sheet = _sheet(packets, "HH-4633")
    assert sheet["role"] == "twin"
    assert sheet["twin_kind"] == "unresolved"
    assert sheet["planted_items"] == []
    assert sheet["explanation"].startswith("Unresolved. Beatriz converted $60,000 from her traditional I")
    assert _sheet(packets, "HH-1587")["explanation"].startswith("A near miss. Daniel made a backdoor Roth")


def test_only_the_published_keys_of_tasks_that_are_not_held(packets: dict[str, dict[str, bytes]]) -> None:
    trap = _sheet(packets, "HH-4821")
    assert [k["task_id"] for k in trap["keys"]] == ["T-REC-01"]
    assert trap["keys"][0]["key"]["amount_misbilled"] == "290.25"
    assert trap["keys"][0]["key"] == json.loads((KEYS / "0.0.1" / "T-REC-01.json").read_text())
    assert [k["task_id"] for k in _sheet(packets, "HH-7350")["keys"]] == ["T-REC-02"]
    for household_id in FEATURED:
        sheet = _sheet(packets, household_id)
        assert sheet["held_until_review"]["task_keys"] == HELD_ON_FEATURED.get(household_id, [])
        if household_id not in ("HH-4821", "HH-7350"):
            assert sheet["keys"] == [], household_id


def test_a_rebuild_is_byte_identical(book: Path) -> None:
    assert case_packets(book, KEYS, TASKS) == case_packets(book, KEYS, TASKS)


def test_a_missing_published_key_is_refused(book: Path, tmp_path: Path) -> None:
    (tmp_path / "0.0.1").mkdir()
    with pytest.raises(PacketError, match="T-REC-01 is not held"):
        case_packets(book, tmp_path, TASKS)


def test_a_file_the_manifest_does_not_list_with_those_bytes_is_refused(book_copy: Path) -> None:
    accounts = book_copy / "households" / "HH-4821" / "custodian" / "accounts.csv"
    accounts.write_text(accounts.read_text() + "\n")
    with pytest.raises(PacketError, match=r"households/HH-4821/custodian/accounts\.csv"):
        case_packets(book_copy, KEYS, TASKS)


def test_a_household_file_outside_the_manifest_stays_out(book_copy: Path) -> None:
    shutil.copyfile(book_copy / "metadata.json", book_copy / "households" / "HH-4821" / "crm" / "stray.json")
    files = read_zip(case_packets(book_copy, KEYS, TASKS)["HH-4821.zip"])
    assert "households/HH-4821/crm/stray.json" not in files
