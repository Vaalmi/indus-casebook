"""Slice 5: the featured pairs for archetypes 7 and 8 stay out of the repo and the site until the freeze."""

import json
import os
import shutil
import sys
import tomllib
from pathlib import Path

import pytest

import casebook.model.archetypes
from casebook.build import ID_LEDGER, BuildError, build_book
from casebook.cli import main
from casebook.generate.script import load_scripts
from casebook.model.archetypes import HELD_OUT_ARCHETYPES, frozen
from casebook.plant import PlantError
from casebook.publish.site_build import SiteBuildError, build_site

from .conftest import README, ROOT, SCRIPTS, SEED

# Everywhere in the public tree a household script or a built book could be copied, outside the
# private folder's place and the build output.
SKIPPED_DIRS = {".git", ".venv", "out", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}


def public_files(suffix: str) -> list[Path]:
    return [p for p in ROOT.rglob(f"*{suffix}") if p.is_file() and not SKIPPED_DIRS & set(p.relative_to(ROOT).parts)]


def test_no_held_out_pair_is_anywhere_in_the_repo() -> None:
    # Reviewer A, slice 5 round 1: only book/scripted was looked at, so a copy elsewhere escaped.
    found: list[str] = []
    for path in public_files(".toml"):
        try:
            raw = tomllib.loads(path.read_text())
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            continue
        if "household_id" in raw and raw.get("archetype") in HELD_OUT_ARCHETYPES:
            found.append(f"{path.relative_to(ROOT)}: {raw['household_id']}")
    for path in public_files("households.json"):
        data = json.loads(path.read_text())
        found += [
            f"{path.relative_to(ROOT)}: {h['household_id']}"
            for h in data.get("households", [])
            if isinstance(h, dict) and h.get("set") == "featured" and h.get("archetype") in HELD_OUT_ARCHETYPES
        ]
    # Slice 12: once the freeze is recorded the held-out pairs move in, and this still passes.
    assert found == [] or frozen(), "archetypes 7 and 8 live in $CASEBOOK_PRIVATE until the freeze"


def test_the_guard_finds_a_held_out_script_copied_anywhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    copy = tmp_path / "tests" / "fixtures" / "held-out"
    copy.mkdir(parents=True)
    (copy / "HH-0007.toml").write_text('household_id = "HH-0007"\narchetype = 7\n')
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    with pytest.raises(AssertionError, match="live in"):
        test_no_held_out_pair_is_anywhere_in_the_repo()


def test_no_held_out_household_is_on_the_site(site: Path) -> None:
    households = json.loads(next((site / "data").rglob("sealed/households.json")).read_text())["households"]
    assert [h["household_id"] for h in households if h["archetype"] in HELD_OUT_ARCHETYPES] == [] or frozen()


def held_out_scripts(tmp_path: Path) -> tuple[Path, Path]:
    """The trap's script, relabelled archetype 7, with a ledger that has not published it."""
    scripts = tmp_path / "scripted"
    shutil.copytree(SCRIPTS, scripts)
    path = scripts / "archetype-10" / "HH-4821.toml"
    path.write_text(path.read_text().replace("archetype = 10\n", "archetype = 7\n", 1))
    ledger = json.loads(ID_LEDGER.read_text())
    del ledger["households"]["HH-4821"]
    ledger["tasks"] = {}
    ledger_path = tmp_path / "id_ledger.json"
    ledger_path.write_text(json.dumps(ledger))
    return scripts, ledger_path


def test_a_public_build_refuses_a_held_out_pair(tmp_path: Path) -> None:
    scripts, ledger = held_out_scripts(tmp_path)
    with pytest.raises(BuildError, match="HH-4821: the featured pairs for archetypes 7 and 8 are held out"):
        build_book(SEED, tmp_path / "book", scripts, ledger=ledger)


def test_a_held_out_build_passes_the_gate_and_is_written_outside_the_repo(tmp_path: Path) -> None:
    scripts, ledger = held_out_scripts(tmp_path)
    # Past the gate, the relabelled script meets archetype 7's planter, which wants its own item.
    with pytest.raises(PlantError, match="archetype 7 plants"):
        build_book(SEED, tmp_path / "book", scripts, ledger=ledger, held_out=True)
    with pytest.raises(BuildError, match="a held-out build is written outside the public repo"):
        build_book(SEED, ROOT / "out" / "held-out-test", scripts, ledger=ledger, held_out=True)


def test_the_freeze_lifts_the_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record = tmp_path / "freeze.json"
    record.write_text("{}")
    monkeypatch.setattr(casebook.model.archetypes, "FREEZE_RECORD", record)
    scripts, ledger = held_out_scripts(tmp_path)
    with pytest.raises(PlantError, match="archetype 7 plants"):
        build_book(SEED, tmp_path / "book", scripts, ledger=ledger)


def test_the_site_refuses_a_held_out_household(book_copy: Path, tmp_path: Path) -> None:
    path = book_copy / "sealed" / "households.json"
    data = json.loads(path.read_text())
    next(h for h in data["households"] if h["household_id"] == "HH-7350")["archetype"] = 8
    path.write_text(json.dumps(data))
    with pytest.raises(SiteBuildError, match="HH-7350: held out until the freeze"):
        build_site(book_copy, tmp_path / "site", README)


def test_a_held_out_build_needs_the_private_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CASEBOOK_PRIVATE", raising=False)
    assert main(["build", "--held-out"]) == 1


PRIVATE_SCRIPTS = Path(os.environ.get("CASEBOOK_PRIVATE", "/nonexistent")) / "book" / "scripted"
PUBLIC = ("src", "tests", "book", "tasks", "docs", "published", "README.md", "AGENTS.md")


@pytest.mark.skipif(not PRIVATE_SCRIPTS.is_dir(), reason="the held-out pairs live in $CASEBOOK_PRIVATE, absent here")
def test_no_public_file_names_a_held_out_household_person_account_or_item() -> None:
    held = [s for s in load_scripts(PRIVATE_SCRIPTS) if s.household.archetype in HELD_OUT_ARCHETYPES]
    assert held
    names = set()
    for script in held:
        hh = script.household
        names |= {hh.household_id, *(p.name for p in hh.members), *(a.account_id for a in hh.accounts)}
        if script.planted is not None:
            names.add(script.planted.item_id)
    files = [p for top in PUBLIC for p in ([ROOT / top] if (ROOT / top).is_file() else (ROOT / top).rglob("*"))]
    found = sorted(
        f"{p.relative_to(ROOT)}: {name}"
        for p in files
        if p.is_file() and "__pycache__" not in p.parts
        for name in names
        if name in p.read_text(encoding="utf-8", errors="ignore")
    )
    assert found == [] or frozen()
