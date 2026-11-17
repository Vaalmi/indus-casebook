"""Slice 12: the freeze. `casebook freeze` records the hashes of every skill, the checklist and every grader, and is
refused while a grader's self-test fails; the runner refuses held-out fixtures with no freeze, or after a skill,
checklist or grader byte changes; once the freeze is recorded the held-out pairs move into the repo and the site.

Nothing here writes `published/freeze.json` or moves anything in the real repo: the record's path and the repo
are temporary ones."""

import dataclasses
import hashlib
import json
import os
import random
import shutil
import sys
import types
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

import casebook.model.archetypes
import casebook.runner.freeze as freeze
from casebook.build import build_book
from casebook.checks import check_book
from casebook.cli import DEFAULT_BOOK, main
from casebook.graders.registry import GRADERS
from casebook.model.archetypes import HELD_OUT_ARCHETYPES, frozen
from casebook.publish.private_set import private_households
from casebook.publish.site_build import build_site
from casebook.runner.config import INSTRUCTIONS, tree_sha256
from casebook.runner.freeze import (
    MoveInError,
    NotFrozenError,
    SelfTest,
    current_hashes,
    freeze_problems,
    ledger_text,
    move_in,
    record_freeze,
    self_test_files,
    self_tests,
)
from casebook.runner.run import prepare
from casebook.seeding import derive_rng
from casebook.site.tasks import MixedFreezeError
from casebook.tasks.task import load_task

from .conftest import BACKGROUND, FEATURED, PUBLIC_HOUSEHOLDS, README, ROOT, SEED, StandIn, held_out_featured

TASKS = ROOT / "tasks" / "public"
SKILL_NAMES = ("compliance-review", "meeting-follow-up", "reconciliation-as-of", "tax-lot-rmd")


def all_pass(files: Mapping[str, Sequence[Path]], root: Path = ROOT) -> dict[str, SelfTest]:
    return {name: SelfTest((f"tests/test_grader_{name}.py",), 3, 0) for name in files}


@pytest.fixture
def record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Where the freeze is recorded, for this test: a temporary file, absent until a test records it."""
    path = tmp_path / "published" / "freeze.json"
    monkeypatch.setattr(casebook.model.archetypes, "FREEZE_RECORD", path)
    return path


@pytest.fixture
def recorded(record: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A freeze recorded on today's bytes, with every self-test passing (they are run for real below)."""
    monkeypatch.setattr(freeze, "self_tests", all_pass)
    record_freeze()
    return record


@pytest.fixture
def held_out_book(real_book: Path, tmp_path: Path) -> Path:
    """The real-ticker build with HH-7350 listed as archetype 8's featured twin: held-out fixtures."""
    copy = tmp_path / "held-out-book"
    shutil.copytree(real_book, copy)
    path = copy / "sealed" / "households.json"
    data = json.loads(path.read_text())
    next(h for h in data["households"] if h["household_id"] == "HH-7350")["archetype"] = 8
    path.write_text(json.dumps(data))
    return copy


def run_args(tmp_path: Path, book: Path) -> list[str]:
    """`casebook run` of T-REC-02, on HH-7350."""
    paths = ["--keys", str(tmp_path / "keys"), "--runs", str(tmp_path / "runs")]
    return ["run", "--task", "T-REC-02", "--arm", "skill", "--book", str(book), "--tasks", str(TASKS), *paths]


# `casebook freeze`: what it records.


def test_the_freeze_hashes_every_skill_the_checklist_and_every_grader() -> None:
    hashes = current_hashes()
    assert set(hashes) == {
        *(f"skill {name}" for name in SKILL_NAMES),
        "skill package",
        "checklist",
        *(f"grader {name}" for name in GRADERS),
        "grader registry",
    }
    # The package and the checklist hash as a run record has them, so a held-out result ties to its freeze.
    assert hashes["skill package"] == tree_sha256(INSTRUCTIONS["skill"])
    assert hashes["checklist"] == tree_sha256(INSTRUCTIONS["checklist"])
    assert hashes["grader fee_reconciliation"] == GRADERS["fee_reconciliation"].sha256()


def test_casebook_freeze_records_the_time_the_hashes_and_each_self_test(
    record: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(freeze, "self_tests", all_pass)
    assert not frozen()
    assert main(["freeze"]) == 0
    assert frozen()
    written = json.loads(record.read_text())
    assert written["hashes"] == current_hashes()
    assert written["recorded_utc"].endswith("+00:00")
    assert set(written["self_tests"]) == set(GRADERS)
    assert {r["result"] for r in written["self_tests"].values()} == {"pass"}
    assert "freeze recorded" in capsys.readouterr().out


def test_casebook_freeze_is_refused_while_a_self_test_fails(
    record: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def one_fails(files: Mapping[str, Sequence[Path]], root: Path = ROOT) -> dict[str, SelfTest]:
        failing = SelfTest(("tests/test_key_rmd.py", "tests/test_grader_rmd_review.py"), 9, 1)
        return all_pass(files) | {"rmd_review": failing}

    monkeypatch.setattr(freeze, "self_tests", one_fails)
    assert main(["freeze"]) == 1
    expected = "grader rmd_review: tests/test_key_rmd.py, tests/test_grader_rmd_review.py: 1 failed, 9 passed"
    assert expected in capsys.readouterr().err
    assert not record.exists()


GOOD = "def test_good() -> None:\n    assert 1 + 1 == 2\n"
BAD = "def test_good() -> None:\n    assert True\n\n\ndef test_bad() -> None:\n    assert 1 + 1 == 3\n"


def test_every_grader_s_self_test_is_its_key_and_grade_modules_test_files() -> None:
    """A grader is its key and its grade module; a book-level grader shares its grade module's tests."""
    for name in GRADERS:
        key_test, grade_test = self_test_files(name)
        assert key_test.is_file() and grade_test.is_file(), name
    assert [f.name for f in self_test_files("billing_groups")] == [
        "test_key_billing_groups.py",
        "test_grader_household_list.py",
    ]
    assert [f.name for f in self_test_files("rmd_review")] == ["test_key_rmd.py", "test_grader_rmd_review.py"]


def test_a_self_test_runs_its_files_in_process(tmp_path: Path, record: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_key_shared.py").write_text(GOOD)
    (tests / "test_grader_alpha.py").write_text(GOOD)
    (tests / "test_grader_beta.py").write_text(BAD)

    def files(name: str, folder: Path = tests) -> tuple[Path, Path]:
        return folder / "test_key_shared.py", folder / f"test_grader_{name}.py"

    results = self_tests({name: files(name) for name in ("alpha", "beta", "gamma")}, tmp_path)
    shared = "tests/test_key_shared.py"
    assert results == {
        "alpha": SelfTest((shared, "tests/test_grader_alpha.py"), 2, 0),
        "beta": SelfTest((shared, "tests/test_grader_beta.py"), 2, 1),
        "gamma": SelfTest((shared, "tests/test_grader_gamma.py"), 1, 0, ("tests/test_grader_gamma.py",)),
    }
    # The freeze runs every grader's self-test: refused, naming each failure, and nothing is recorded.
    spec = GRADERS["fee_reconciliation"]
    graders = {name: dataclasses.replace(spec, name=name) for name in ("alpha", "beta", "gamma")}
    monkeypatch.setattr(freeze, "GRADERS", graders)
    monkeypatch.setattr(freeze, "self_test_files", files)
    with pytest.raises(freeze.FreezeRefusedError) as refused:
        record_freeze(tests=tests)
    assert str(refused.value).splitlines()[1:] == [
        f"grader beta: {shared}, tests/test_grader_beta.py: 1 failed, 2 passed",
        "grader gamma: no self-test (tests/test_grader_gamma.py missing)",
    ]
    assert not record.exists()
    (tests / "test_grader_beta.py").write_text(GOOD)
    (tests / "test_grader_gamma.py").write_text(GOOD)
    written = record_freeze(tests=tests)
    assert {name: r["result"] for name, r in written["self_tests"].items()} == dict.fromkeys(graders, "pass")
    assert json.loads(record.read_text()) == written


# The runner refuses held-out fixtures unless the freeze matches.


def test_the_runner_refuses_held_out_fixtures_with_no_freeze(
    held_out_book: Path, record: Path, tmp_path: Path, standin_cli: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(run_args(tmp_path, held_out_book)) == 2
    err = capsys.readouterr().err
    assert "NotFrozenError: task T-REC-02 reads held-out fixtures (HH-7350) and no freeze is recorded" in err
    # Refused before the key is computed: no key, no run.
    assert not (tmp_path / "keys").exists() and not (tmp_path / "runs").exists()
    assert not standin_cli.log.exists()


def test_the_prepare_step_refuses_them_too(held_out_book: Path, record: Path, tmp_path: Path) -> None:
    with pytest.raises(NotFrozenError, match="no freeze is recorded"):
        prepare(load_task(TASKS / "T-REC-02.toml"), held_out_book, tmp_path / "workspace", None)


def test_a_matching_freeze_lets_a_held_out_task_run(held_out_book: Path, recorded: Path) -> None:
    assert freeze_problems(load_task(TASKS / "T-REC-02.toml"), held_out_book) == []


def copy_of(source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> Path:
    copy = tmp_path / source.name
    shutil.copytree(source, copy)
    monkeypatch.setattr(freeze, name, copy)
    return copy


def change_a_byte(path: Path) -> None:
    path.write_bytes(path.read_bytes() + b" ")


def test_the_runner_refuses_held_out_fixtures_after_a_skill_byte_changes(
    held_out_book: Path,
    record: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    standin_cli: StandIn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    skills = copy_of(freeze.SKILLS, tmp_path, monkeypatch, "SKILLS")
    monkeypatch.setattr(freeze, "self_tests", all_pass)
    record_freeze()
    task = load_task(TASKS / "T-REC-02.toml")
    assert freeze_problems(task, held_out_book) == []
    change_a_byte(skills / "skills" / "reconciliation-as-of" / "SKILL.md")
    assert freeze_problems(task, held_out_book) == [
        "task T-REC-02 reads held-out fixtures (HH-7350): skill package differs from the freeze",
        "task T-REC-02 reads held-out fixtures (HH-7350): skill reconciliation-as-of differs from the freeze",
    ]
    assert main(run_args(tmp_path, held_out_book)) == 2
    assert "skill reconciliation-as-of differs from the freeze" in capsys.readouterr().err
    assert not (tmp_path / "keys").exists()


def test_the_runner_refuses_held_out_fixtures_after_a_checklist_byte_changes(
    held_out_book: Path, record: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checklist = copy_of(freeze.CHECKLIST, tmp_path, monkeypatch, "CHECKLIST")
    monkeypatch.setattr(freeze, "self_tests", all_pass)
    record_freeze()
    change_a_byte(checklist / ".claude-plugin" / "plugin.json")
    assert freeze_problems(load_task(TASKS / "T-REC-02.toml"), held_out_book) == [
        "task T-REC-02 reads held-out fixtures (HH-7350): checklist differs from the freeze"
    ]


def test_the_runner_refuses_held_out_fixtures_after_a_grader_byte_changes(
    held_out_book: Path, record: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Not T-REC-02's own grader: a change to any grader unfreezes every held-out run.
    spec = GRADERS["rmd_review"]
    sources = tmp_path / "grader"
    sources.mkdir()
    copies = tuple(Path(shutil.copy(p, sources / p.name)) for p in spec.sources)
    monkeypatch.setitem(GRADERS, "rmd_review", dataclasses.replace(spec, sources=copies))
    monkeypatch.setattr(freeze, "self_tests", all_pass)
    record_freeze()
    change_a_byte(copies[-1])
    assert freeze_problems(load_task(TASKS / "T-REC-02.toml"), held_out_book) == [
        "task T-REC-02 reads held-out fixtures (HH-7350): grader rmd_review differs from the freeze"
    ]


def test_a_grader_dropped_since_the_freeze_is_named(held_out_book: Path, recorded: Path) -> None:
    data = json.loads(recorded.read_text())
    data["hashes"]["grader retired"] = "0" * 64
    recorded.write_text(json.dumps(data))
    assert freeze_problems(load_task(TASKS / "T-REC-02.toml"), held_out_book) == [
        "task T-REC-02 reads held-out fixtures (HH-7350): grader retired is in the freeze but no longer exists"
    ]


def test_a_public_task_on_public_fixtures_is_unaffected(real_book: Path, held_out_book: Path, record: Path) -> None:
    # No freeze is recorded: a featured task, and before the freeze a book-level task, on the public book run as
    # before. Once archetypes 7 and 8's pairs are moved in, the public book holds them and a book-level task
    # reads them: it then needs the freeze to match, like any held-out run.
    assert freeze_problems(load_task(TASKS / "T-REC-01.toml"), real_book) == []
    assert (freeze_problems(load_task(TASKS / "T-REC-05.toml"), real_book) == []) == (held_out_featured() == ())
    # A book-level task on a book that holds a held-out household reads it, so it is held out too.
    held = ", ".join(sorted({"HH-7350", *held_out_featured()}))
    assert freeze_problems(load_task(TASKS / "T-REC-05.toml"), held_out_book) == [
        f"task T-REC-05 reads held-out fixtures ({held}) and no freeze is recorded "
        f"({record}): the owner runs `casebook freeze` first"
    ]


def test_a_private_pair_s_fixtures_are_held_out_too(real_book: Path, record: Path) -> None:
    household = sorted(private_households())[0]
    task = dataclasses.replace(load_task(TASKS / "T-REC-01.toml"), household_id=household)
    [problem] = freeze_problems(task, real_book)
    assert f"reads held-out fixtures ({household}) and no freeze is recorded" in problem


# Moving the held-out pairs in.


def script(household: str, archetype: int, pair: int, role: str) -> str:
    return f'household_id = "{household}"\narchetype = {archetype}\npair = {pair}\nrole = "{role}"\n'


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo copy with the book's ledger and its scripts as before the freeze: the held-out pairs absent."""
    root = tmp_path / "repo"
    (root / "book").mkdir(parents=True)
    ledger = json.loads((ROOT / "book" / "id_ledger.json").read_text())
    for household in held_out_featured():
        del ledger["households"][household]
    (root / "book" / "id_ledger.json").write_text(ledger_text(ledger))
    held = [f"archetype-{a}" for a in HELD_OUT_ARCHETYPES]
    shutil.copytree(ROOT / "book" / "scripted", root / "book" / "scripted", ignore=lambda folder, names: held)
    return root


@pytest.fixture
def private(tmp_path: Path) -> Path:
    """Invented held-out pairs (IDs the book does not use), each folder with its hand-worked values beside it."""
    root = tmp_path / "private"
    for archetype, (trap, twin) in {7: ("HH-7001", "HH-7002"), 8: ("HH-8001", "HH-8002")}.items():
        folder = root / "book" / "scripted" / f"archetype-{archetype}"
        folder.mkdir(parents=True)
        (folder / f"{trap}.toml").write_text(script(trap, archetype, 1, "trap"))
        (folder / f"{twin}.toml").write_text(script(twin, archetype, 1, "twin"))
        (folder / "expected.json").write_text("{}\n")
    return root


def test_the_move_in_is_refused_with_no_freeze(repo: Path, private: Path, record: Path) -> None:
    before = (repo / "book" / "id_ledger.json").read_text()
    with pytest.raises(MoveInError, match="no freeze is recorded"):
        move_in(private, repo)
    assert not (repo / "book" / "scripted" / "archetype-7").exists()
    assert (repo / "book" / "id_ledger.json").read_text() == before


def test_the_move_in_copies_the_pairs_and_adds_them_to_the_ledger(repo: Path, private: Path, recorded: Path) -> None:
    before = json.loads((repo / "book" / "id_ledger.json").read_text())
    assert move_in(private, repo) == ["HH-7001", "HH-7002", "HH-8001", "HH-8002"]
    for archetype in HELD_OUT_ARCHETYPES:
        moved = repo / "book" / "scripted" / f"archetype-{archetype}"
        assert sorted(p.name for p in moved.iterdir()) == sorted(
            p.name for p in (private / "book" / "scripted" / moved.name).iterdir()
        )
    after = json.loads((repo / "book" / "id_ledger.json").read_text())
    added = {h: e for h, e in after["households"].items() if h not in before["households"]}
    assert added == {
        "HH-7001": {"archetype": 7, "pair": 1, "role": "trap"},
        "HH-7002": {"archetype": 7, "pair": 1, "role": "twin"},
        "HH-8001": {"archetype": 8, "pair": 1, "role": "trap"},
        "HH-8002": {"archetype": 8, "pair": 1, "role": "twin"},
    }
    assert {h: after["households"][h] for h in before["households"]} == before["households"]
    assert after["tasks"] == before["tasks"]
    # Written as the repo writes it: one entry a line, in ID order.
    assert (
        '    "HH-7001": { "archetype": 7, "pair": 1, "role": "trap" },\n'
        in (repo / "book" / "id_ledger.json").read_text()
    )
    # Once only.
    with pytest.raises(MoveInError, match="already in the repo"):
        move_in(private, repo)


@pytest.mark.parametrize(
    ("archetype", "pair"),
    [(4, 2), (7, 2)],  # a private pair's script; a background pair's
)
def test_the_move_in_moves_held_out_featured_pairs_only(
    repo: Path, private: Path, recorded: Path, archetype: int, pair: int
) -> None:
    folder = private / "book" / "scripted" / "archetype-7"
    (folder / "HH-7003.toml").write_text(script("HH-7003", archetype, pair, "trap"))
    with pytest.raises(MoveInError, match=f"HH-7003 is archetype {archetype}, pair {pair}, not a held-out pair"):
        move_in(private, repo)
    assert not (repo / "book" / "scripted" / "archetype-7").exists()


def test_the_move_in_keeps_a_published_id_s_meaning(repo: Path, private: Path, recorded: Path) -> None:
    folder = private / "book" / "scripted" / "archetype-7"
    (folder / "HH-7001.toml").unlink()
    (folder / "HH-4821.toml").write_text(script("HH-4821", 7, 1, "trap"))
    with pytest.raises(MoveInError, match="HH-4821 is in the ledger as"):
        move_in(private, repo)


def test_casebook_freeze_move_in(
    repo: Path, private: Path, record: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(freeze, "REPO", repo)
    monkeypatch.setenv("CASEBOOK_PRIVATE", str(private))
    assert main(["freeze", "--move-in"]) == 1
    assert "move-in refused: no freeze is recorded" in capsys.readouterr().err
    monkeypatch.setattr(freeze, "self_tests", all_pass)
    assert main(["freeze"]) == 0
    assert main(["freeze", "--move-in"]) == 0
    assert "HH-7001, HH-7002, HH-8001, HH-8002" in capsys.readouterr().out
    assert (repo / "book" / "scripted" / "archetype-8" / "HH-8002.toml").is_file()


def test_the_ledger_is_rewritten_byte_for_byte() -> None:
    path = ROOT / "book" / "id_ledger.json"
    assert ledger_text(json.loads(path.read_text())) == path.read_text()


def test_the_public_book_counts_16_featured_before_the_freeze_and_20_after() -> None:
    assert len(FEATURED) == (20 if frozen() else 16)
    assert len(FEATURED) + BACKGROUND == PUBLIC_HOUSEHOLDS


PRIVATE_SCRIPTS = Path(os.environ.get("CASEBOOK_PRIVATE", "/nonexistent")) / "book" / "scripted"


@pytest.mark.skipif(not PRIVATE_SCRIPTS.is_dir(), reason="the held-out pairs live in $CASEBOOK_PRIVATE, absent here")
def test_once_frozen_the_held_out_pairs_move_in_build_and_reach_the_site(
    repo: Path, recorded: Path, tmp_path: Path
) -> None:
    moved = move_in(PRIVATE_SCRIPTS.parents[1], repo)
    assert len(moved) == 4
    book = tmp_path / "book" / "0.0.1"
    result = build_book(
        SEED, book, repo / "book" / "scripted", ledger=repo / "book" / "id_ledger.json", background=True
    )
    assert len(result.households) == 92 and set(moved) < set(result.households)
    sealed = json.loads((book / "sealed" / "households.json").read_text())["households"]
    featured = sorted(h["household_id"] for h in sealed if h["set"] == "featured")
    assert len(featured) == 20 and set(moved) < set(featured)
    assert check_book(book).passed
    site = tmp_path / "site"
    build_site(book, site, README)
    assert all((site / "households" / f"{household}.html").is_file() for household in moved)
    # The slice 5 tests pass with them present, now that the freeze is recorded.
    from .test_held_out import test_no_held_out_household_is_on_the_site

    test_no_held_out_household_is_on_the_site(site)


# The hand audit's commands, which call the audit builder's module.


def test_casebook_audit_sheet_and_audit_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[object, ...]] = []
    problems: list[str] = []

    def write_audit_sheet(book: Path, out: Path, rng: random.Random) -> list[Path]:
        calls.append((book, out, rng.random()))
        return [out / "0.0.1" / "worksheet.csv", out / "0.0.1" / "worksheet.md"]

    def audit_log_problems(log: Path, worksheet: Path) -> list[str]:
        calls.append((log, worksheet))
        return problems

    sheet = types.ModuleType("casebook.checks.audit_sheet")
    sheet.write_audit_sheet = write_audit_sheet  # type: ignore[attr-defined]
    log = types.ModuleType("casebook.checks.audit_log")
    log.audit_log_problems = audit_log_problems  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "casebook.checks.audit_sheet", sheet)
    monkeypatch.setitem(sys.modules, "casebook.checks.audit_log", log)
    assert main(["audit-sheet"]) == 0
    # The draw is seeded: the audit's own stream of the seed, 2026 by default.
    assert calls.pop() == (DEFAULT_BOOK, Path("out/audit"), derive_rng("audit", 2026).random())
    assert "wrote 2 files" in capsys.readouterr().out
    assert main(["audit-sheet", "--book", str(tmp_path), "--out", str(tmp_path / "a"), "--seed", "7"]) == 0
    assert calls.pop() == (tmp_path, tmp_path / "a", derive_rng("audit", 7).random())
    assert main(["audit-log", "--check"]) == 0
    assert calls.pop() == (Path("published/audit/audit-log.csv"), Path("out/audit/0.0.1/worksheet.csv"))
    problems.append("HH-0120 line 4: no result")
    assert main(["audit-log", "--check"]) == 1
    assert "HH-0120 line 4: no result" in capsys.readouterr().err


# Reviewers A and B, slice 12 round 1.


def test_a_follow_up_task_reaches_every_household_through_the_crm(held_out_book: Path, record: Path) -> None:
    """The CRM sandbox holds every household's CRM, so a follow-up task on a public household reads the held-out
    ones too, and needs the freeze."""
    follow_up = load_task(TASKS / "T-MTG-01.toml")
    [problem] = freeze_problems(follow_up, held_out_book)
    assert "task T-MTG-01 reads held-out fixtures (" in problem and "HH-7350" in problem
    # Without the CRM's tools, the same task reads its own household only.
    read_only = dataclasses.replace(follow_up, allowed_tools=("Read", "Glob", "Grep"))
    assert freeze_problems(read_only, held_out_book) == []


def test_the_freeze_covers_the_grader_registry(
    held_out_book: Path, recorded: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Which key and grade function a grader name runs is the registry's: a byte of it changed unfreezes."""
    copy = tmp_path / "registry.py"
    shutil.copy(freeze.REGISTRY, copy)
    monkeypatch.setattr(freeze, "REGISTRY", copy)
    task = load_task(TASKS / "T-REC-02.toml")
    assert freeze_problems(task, held_out_book) == []
    change_a_byte(copy)
    assert freeze_problems(task, held_out_book) == [
        "task T-REC-02 reads held-out fixtures (HH-7350): grader registry differs from the freeze"
    ]


def test_an_interrupted_self_test_session_refuses_the_freeze(tmp_path: Path, record: Path) -> None:
    """Reviewer A, slice 12 round 1: passes tallied before an interrupt counted as a complete self-test."""
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_grader_alpha.py").write_text(GOOD)
    (tests / "test_grader_beta.py").write_text("def test_stop() -> None:\n    raise KeyboardInterrupt\n")
    files = {"alpha": [tests / "test_grader_alpha.py"], "beta": [tests / "test_grader_beta.py"]}
    with pytest.raises(freeze.FreezeRefusedError, match="did not run to its end"):
        self_tests(files, tmp_path)
    assert not record.exists()


def test_a_run_records_the_freeze_it_ran_under(record: Path, recorded: Path) -> None:
    assert freeze.freeze_identity() == hashlib.sha256(recorded.read_bytes()).hexdigest()
    assert freeze.freeze_identity(record.parent / "absent.json") is None


def test_a_task_page_refuses_arms_from_two_freezes(book: Path, tmp_path: Path) -> None:
    """Results from two freezes are never shown side by side (the plan's freeze table)."""
    from .test_held_verdicts import a_graded_record

    runs = tmp_path / "runs" / "T-REC-05"
    runs.mkdir(parents=True)
    old = a_graded_record("T-REC-05") | {"arm": "basic", "freeze": "a" * 64}
    new = a_graded_record("T-REC-05") | {"arm": "skill", "freeze": "b" * 64, "run_id": "T-REC-05-skill-later"}
    for record in (old, new):
        (runs / f"{record['run_id']}.json").write_text(json.dumps(record))
    with pytest.raises(MixedFreezeError, match="ran under different freezes"):
        build_site(book, tmp_path / "site", README, tmp_path / "runs", TASKS, None)
    new["freeze"] = "a" * 64
    (runs / f"{new['run_id']}.json").write_text(json.dumps(new))
    build_site(book, tmp_path / "site", README, tmp_path / "runs", TASKS, None)


def test_a_run_keeps_the_freeze_and_hashes_it_started_under(
    real_book: Path, standin_cli: StandIn, recorded: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reviewers A and B, slice 12 round 2: the record read the freeze, and the skill's hash, after the CLI
    finished, so a freeze recorded (or a skill changed) while it ran relabelled its output."""
    import casebook.runner.run as run_module
    from casebook.runner.config import SharedConfig
    from casebook.runner.run import RunInputs, private_root, run_task

    skills = tmp_path / "skills-copy"
    shutil.copytree(INSTRUCTIONS["skill"] or "", skills)  # pyright: ignore[reportArgumentType]
    monkeypatch.setitem(run_module.INSTRUCTIONS, "skill", skills)
    started_freeze, started_skill = freeze.freeze_identity(), tree_sha256(skills)
    launch = run_module.start

    def while_it_runs(*args: Any, **kwargs: Any) -> Any:
        done = launch(*args, **kwargs)
        recorded.write_text(recorded.read_text() + "\n")  # the owner records a new freeze meanwhile
        change_a_byte(next(skills.rglob("SKILL.md")))
        return done

    monkeypatch.setattr(run_module, "start", while_it_runs)
    task = load_task(TASKS / "T-REC-01.toml")
    record = run_task(RunInputs(task, "skill", real_book, None, "g", "k"), SharedConfig(retries=0), private_root())
    assert record["state"] == "completed", record["errors"]
    assert record["freeze"] == started_freeze != freeze.freeze_identity()
    assert record["hashes"]["skill"] == started_skill != tree_sha256(skills)


def test_a_retry_s_output_carries_the_freeze_and_hashes_it_ran_under(
    real_book: Path, standin_cli: StandIn, recorded: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reviewers A and B, slice 12 targeted check: inputs taken once before the first attempt labelled a retry
    that ran after a new freeze with the first attempt's freeze and hashes."""
    import casebook.runner.run as run_module
    from casebook.runner.cli import Completed
    from casebook.runner.config import SharedConfig
    from casebook.runner.run import RunInputs, private_root, run_task

    skills = tmp_path / "skills-copy"
    shutil.copytree(INSTRUCTIONS["skill"] or "", skills)  # pyright: ignore[reportArgumentType]
    monkeypatch.setitem(run_module.INSTRUCTIONS, "skill", skills)
    first_freeze, first_skill = freeze.freeze_identity(), tree_sha256(skills)
    launch = run_module.start
    calls: list[int] = []

    def first_fails(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            # The first attempt fails; before the retry the owner changes a skill and records a new freeze.
            change_a_byte(next(skills.rglob("SKILL.md")))
            recorded.write_text(recorded.read_text() + "\n")
            return Completed(1, "", "error: overloaded", False)
        return launch(*args, **kwargs)

    monkeypatch.setattr(run_module, "start", first_fails)
    task = load_task(TASKS / "T-REC-01.toml")
    record = run_task(RunInputs(task, "skill", real_book, None, "g", "k"), SharedConfig(retries=1), private_root())
    assert record["state"] == "completed" and len(record["attempts"]) == 2, record["errors"]
    assert record["freeze"] == freeze.freeze_identity() != first_freeze
    assert record["hashes"]["skill"] == tree_sha256(skills) != first_skill
