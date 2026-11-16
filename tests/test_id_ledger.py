"""Slice 4: the ID ledger; a published ID keeps its archetype, pair and role, or the build fails."""

import json
import shutil
from pathlib import Path

import pytest

from casebook.build import ID_LEDGER, BuildError, build_book
from casebook.model.ledger import LedgerError, LedgerHousehold, LedgerTask, load_ledger, parse_ledger
from casebook.tasks.task import load_task

from .conftest import FEATURED, ROOT, SCRIPTS, SEED


def test_the_ledger_is_committed_with_the_published_ids() -> None:
    ledger = load_ledger(ROOT / "book" / "id_ledger.json")
    assert ID_LEDGER == ROOT / "book" / "id_ledger.json"
    # The 16 public featured households, published with slice 5; archetypes 7 and 8 are held out.
    pairs = {
        1: ("HH-1204", "HH-1587"),
        2: ("HH-2316", "HH-2749"),
        3: ("HH-3058", "HH-3462"),
        4: ("HH-4105", "HH-4633"),
        5: ("HH-5271", "HH-5814"),
        6: ("HH-6047", "HH-6590"),
        9: ("HH-9234", "HH-9571"),
        10: ("HH-4821", "HH-7350"),
    }
    featured = {hh: entry for hh, entry in ledger.households.items() if entry.pair == 1}
    assert featured == {
        hh: LedgerHousehold(archetype=a, pair=1, role=role)
        for a, both in pairs.items()
        for hh, role in zip(both, ("trap", "twin"), strict=True)
    }
    # And the 80 background households of slice 6, drawn from seed 2026: pairs 2 to 5 of every archetype.
    background = {hh: entry for hh, entry in ledger.households.items() if entry.pair != 1}
    assert len(background) == 80 and all(100 <= int(hh.removeprefix("HH-")) <= 999 for hh in background)
    assert sorted((e.archetype, e.pair, e.role) for e in background.values()) == sorted(
        (a, n, role) for a in range(1, 11) for n in range(2, 6) for role in ("trap", "twin")
    )
    assert ledger.tasks == {"T-REC-01": LedgerTask("HH-4821", "reconciliation")}


def test_every_built_household_and_every_task_file_is_in_the_ledger(full_book: Path) -> None:
    ledger = load_ledger(ID_LEDGER)
    manifest = json.loads((full_book / "manifest.json").read_text())
    assert {h["household_id"] for h in manifest["households"]} <= set(ledger.households)
    for path in sorted((ROOT / "tasks" / "public").glob("*.toml")):
        task = load_task(path)
        assert task.task_id in ledger.tasks, task.task_id
        ledger.check_task(task.task_id, task.household_id, task.workflow)


def edited_scripts(tmp_path: Path, old: str, new: str) -> Path:
    scripts = tmp_path / "scripted"
    shutil.copytree(SCRIPTS, scripts)
    path = scripts / "archetype-10" / "HH-4821.toml"
    text = path.read_text()
    assert text.count(old) == 1
    path.write_text(text.replace(old, new))
    return scripts


@pytest.mark.parametrize(
    ("old", "new", "made"),
    [
        ("archetype = 10\n", "archetype = 9\n", "archetype 9, pair 1, trap"),
        ("pair = 1\n", "pair = 2\n", "archetype 10, pair 2, trap"),
    ],
)
def test_changing_a_published_households_archetype_or_pair_fails_the_build(
    tmp_path: Path, old: str, new: str, made: str
) -> None:
    with pytest.raises(
        BuildError, match=f"HH-4821 is published as archetype 10, pair 1, trap; the script makes it {made}"
    ):
        build_book(SEED, tmp_path / "book", edited_scripts(tmp_path, old, new))
    assert not (tmp_path / "book").exists()


def test_changing_a_published_households_role_fails_the_build(tmp_path: Path) -> None:
    # A script cannot turn a trap into a twin without rewriting it, so the ledger is edited instead.
    ledger = json.loads(ID_LEDGER.read_text())
    ledger["households"]["HH-4821"]["role"] = "twin"
    path = tmp_path / "id_ledger.json"
    path.write_text(json.dumps(ledger))
    with pytest.raises(BuildError, match=r"published as archetype 10, pair 1, twin; the script makes it .* trap"):
        build_book(SEED, tmp_path / "book", SCRIPTS, ledger=path)


def test_a_household_not_yet_published_builds(tmp_path: Path) -> None:
    ledger = json.loads(ID_LEDGER.read_text())
    del ledger["households"]["HH-7350"]
    path = tmp_path / "id_ledger.json"
    path.write_text(json.dumps(ledger))
    assert build_book(SEED, tmp_path / "book", SCRIPTS, ledger=path).households == FEATURED


def test_a_build_without_the_ledger_fails(tmp_path: Path) -> None:
    with pytest.raises(BuildError, match="the ID ledger is missing"):
        build_book(SEED, tmp_path / "book", SCRIPTS, ledger=tmp_path / "nowhere.json")


def test_a_task_keeps_its_published_household_and_workflow() -> None:
    ledger = load_ledger(ID_LEDGER)
    with pytest.raises(LedgerError, match="T-REC-01 is published as reconciliation on HH-4821"):
        ledger.check_task("T-REC-01", "HH-7350", "reconciliation")


def test_the_ledger_refuses_a_task_on_a_household_it_does_not_hold() -> None:
    raw = {"households": {}, "tasks": {"T-REC-09": {"household_id": "HH-0001", "workflow": "reconciliation"}}}
    with pytest.raises(LedgerError, match="does not hold"):
        parse_ledger(raw, "ledger.json")


def test_a_malformed_ledger_is_refused() -> None:
    with pytest.raises(LedgerError, match="malformed"):
        parse_ledger({"households": {"HH-1": {"archetype": "ten"}}, "tasks": {}}, "ledger.json")
