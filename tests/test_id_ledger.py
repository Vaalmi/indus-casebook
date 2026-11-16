"""Slice 4: the ID ledger; a published ID keeps its archetype, pair and role, or the build fails."""

import json
import shutil
from pathlib import Path

import pytest

from casebook.build import ID_LEDGER, BuildError, build_book
from casebook.model.ledger import LedgerError, LedgerHousehold, LedgerTask, load_ledger, parse_ledger
from casebook.tasks.task import load_task

from .conftest import ROOT, SCRIPTS, SEED


def test_the_ledger_is_committed_with_the_published_ids() -> None:
    ledger = load_ledger(ROOT / "book" / "id_ledger.json")
    assert ID_LEDGER == ROOT / "book" / "id_ledger.json"
    assert ledger.households == {
        "HH-4821": LedgerHousehold(archetype=10, pair=1, role="trap"),
        "HH-7350": LedgerHousehold(archetype=10, pair=1, role="twin"),
    }
    assert ledger.tasks == {"T-REC-01": LedgerTask("HH-4821", "reconciliation")}


def test_every_built_household_and_every_task_file_is_in_the_ledger(book: Path) -> None:
    ledger = load_ledger(ID_LEDGER)
    manifest = json.loads((book / "manifest.json").read_text())
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
    assert build_book(SEED, tmp_path / "book", SCRIPTS, ledger=path).households == ("HH-4821", "HH-7350")


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
