"""The freeze (docs/SPEC.md, Words: "the recorded hashes of skills and graders before held-out pairs run").

`casebook freeze` (the owner) records the hash of every skill, of the skill package and the checklist as a run
loads them, and of every grader, with the UTC time and each grader's self-test result. It is refused while any
grader's self-test fails. A grader's **self-test** is the test files of the two modules that make it, its key
module and its grade module: `tests/test_key_<key module>.py` and `tests/test_grader_<grade module>.py`, run
in-process (a book-level grader shares its grade module, `household_list` or `compliance_review`, with others,
so their shared test file is part of each one's self-test). A grader missing either file fails its self-test.

The runner refuses **held-out fixtures** unless the freeze matches today's hashes (docs/SPEC.md, Rules: "Freeze
before held-out runs"). A task's fixtures are held out when its household is in a held-out pair (the featured
pairs of `HELD_OUT_ARCHETYPES`) or in a private pair (`PRIVATE_PAIRS`: the private set runs only after the freeze
too); a book-level task's, when the book holds any such household. A skill, checklist or grader byte changed
since the record unfreezes them until the owner records the freeze again.

Once the freeze is recorded, `casebook freeze --move-in` moves the held-out pairs from `$CASEBOOK_PRIVATE` into
`book/scripted/` and adds their households to the public ID ledger; never a private pair.
"""

import hashlib
import json
import shutil
import sys
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from casebook.graders import registry
from casebook.graders.registry import GRADERS
from casebook.model import archetypes
from casebook.model.archetypes import HELD_OUT_ARCHETYPES, PRIVATE_PAIRS
from casebook.model.files import read_manifest
from casebook.model.ledger import BOOK, load_ledger
from casebook.publish.private_set import private_households
from casebook.runner.config import CRM_TOOLS, INSTRUCTIONS, REPO, tree_sha256
from casebook.runner.preflight import RunRefusedError
from casebook.tasks.task import Task

# The instruction packages a run loads and records (runner.config); the freeze hashes the same trees.
SKILLS = INSTRUCTIONS["skill"] or REPO / "skills" / "indus-advisor"
CHECKLIST = INSTRUCTIONS["checklist"] or REPO / "checklist" / "indus-checklist"
TESTS = REPO / "tests"
LEDGER = REPO / "book" / "id_ledger.json"
SCRIPTED = Path("book") / "scripted"
# The featured pair of each archetype is pair 1 (the ledger's numbering); archetypes 7 and 8's are held out.
FEATURED_PAIR = 1
REGISTRY = Path(registry.__file__ or "")


def self_test_files(grader: str, tests: Path = TESTS) -> tuple[Path, Path]:
    """A grader's self-test: the test files of its key module (the registry lists it first among a grader's
    sources) and of its grade module."""
    spec = GRADERS[grader]
    grade_module = spec.grade.__module__.rsplit(".", 1)[-1]
    return tests / f"test_key_{spec.sources[0].stem}.py", tests / f"test_grader_{grade_module}.py"


def current_hashes(skills: Path | None = None, checklist: Path | None = None) -> dict[str, str]:
    """Every skill's tree hash, the skill package's and the checklist's as a run records them, and every
    grader's. The package's covers what no single skill folder does: its plugin.json, which the CLI reads."""
    skills, checklist = skills or SKILLS, checklist or CHECKLIST
    hashes = {
        f"skill {folder.name}": _tree(folder)
        for folder in sorted(p for p in (skills / "skills").iterdir() if p.is_dir())
    }
    hashes["skill package"] = _tree(skills)
    hashes["checklist"] = _tree(checklist)
    hashes |= {f"grader {name}": GRADERS[name].sha256() for name in sorted(GRADERS)}
    # Which key and grade function each grader name runs, and with what parameters, is the registry's: its bytes
    # are part of the freeze, though no single grader's sources list it (reviewers A and B, slice 12 round 1).
    hashes["grader registry"] = hashlib.sha256(REGISTRY.read_bytes()).hexdigest()
    return hashes


def _tree(path: Path) -> str:
    digest = tree_sha256(path)
    assert digest is not None
    return digest


@dataclass(frozen=True)
class SelfTest:
    files: tuple[str, ...]
    passed: int
    failed: int
    missing: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.passed > 0 and self.failed == 0 and not self.missing

    def problem(self) -> str:
        if self.missing:
            return f"no self-test ({', '.join(self.missing)} missing)"
        return f"{', '.join(self.files)}: {self.failed} failed, {self.passed} passed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "files": list(self.files),
            "passed": self.passed,
            "failed": self.failed,
            "result": "pass" if self.ok else "fail",
        }


class _Tally:
    """Counts each test file's passes and failures (a failed collection or fixture counts as a failure)."""

    def __init__(self) -> None:
        self.counts: dict[str, list[int]] = {}

    def _add(self, nodeid: str, index: int) -> None:
        name = Path(nodeid.split("::")[0]).name
        self.counts.setdefault(name, [0, 0])[index] += 1

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.failed:
            self._add(report.nodeid, 1)
        elif report.passed and report.when == "call":
            self._add(report.nodeid, 0)

    def pytest_collectreport(self, report: Any) -> None:
        if report.failed:
            self._add(report.nodeid, 1)


def _forget(files: Iterable[Path]) -> None:
    """Drop a self-test module already imported in this process, so its file's bytes today are what runs."""
    targets = {f.resolve() for f in files}
    for name, module in list(sys.modules.items()):
        source = getattr(module, "__file__", None)
        if source and Path(source).resolve() in targets:
            del sys.modules[name]


def self_tests(files: Mapping[str, Sequence[Path]], root: Path = REPO) -> dict[str, SelfTest]:
    """Run each grader's self-test files (`files`, by grader) in this process, all in one pytest session, and
    tally each grader's: a file shared by several graders runs once and counts for each."""
    import pytest

    every = {f for grader_files in files.values() for f in grader_files}
    present = sorted({f.as_posix() for f in every if f.is_file()})
    _forget(every)
    tally = _Tally()
    if present:
        code = pytest.main([*present, "-q", "-p", "no:cacheprovider", "--no-cov"], plugins=[tally])
        # Only a session that ran to its end counts: an interrupted one, or one that could not collect or start,
        # has tallied passes for files it never finished (reviewer A, slice 12 round 1).
        if code not in (pytest.ExitCode.OK, pytest.ExitCode.TESTS_FAILED):
            raise FreezeRefusedError(f"the self-test session did not run to its end (pytest exit code {int(code)})")
    results: dict[str, SelfTest] = {}
    for name, grader_files in files.items():
        counts = [tally.counts.get(f.name, [0, 0]) for f in grader_files if f.is_file()]
        results[name] = SelfTest(
            files=tuple(_shown(f, root) for f in grader_files),
            passed=sum(c[0] for c in counts),
            failed=sum(c[1] for c in counts),
            missing=tuple(_shown(f, root) for f in grader_files if not f.is_file()),
        )
    return results


def _shown(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()


class FreezeRefusedError(RuntimeError):
    pass


def record_freeze(path: Path | None = None, tests: Path = TESTS) -> dict[str, Any]:
    """Record the freeze, unless a grader's self-test fails (naming each that does)."""
    path = path or archetypes.FREEZE_RECORD
    results = self_tests({name: self_test_files(name, tests) for name in sorted(GRADERS)}, tests.parent)
    failing = [f"grader {name}: {result.problem()}" for name, result in sorted(results.items()) if not result.ok]
    if failing:
        raise FreezeRefusedError("the freeze is refused while a grader's self-test fails:\n" + "\n".join(failing))
    record = {
        "recorded_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "hashes": current_hashes(),
        "self_tests": {name: r.to_dict() for name, r in sorted(results.items())},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def freeze_identity(record: Path | None = None) -> str | None:
    """The freeze a run ran under: the sha256 of the freeze record, or None before any freeze. A run record keeps
    it, so results from two freezes are never shown as one (docs/PLAN.md, the freeze's state table)."""
    record = record or archetypes.FREEZE_RECORD
    return hashlib.sha256(record.read_bytes()).hexdigest() if record.is_file() else None


def held_out_households(book: Path, ledger: Path = LEDGER) -> frozenset[str]:
    """The households whose fixtures are held out: the held-out featured pairs' (from the book's sealed list, or
    the ledger once they are published) and the private pairs'. Without a sealed list, every household of a
    held-out archetype in the book counts."""
    sealed = book / "sealed" / "households.json"
    if sealed.is_file():
        listed = json.loads(sealed.read_text(encoding="utf-8"))["households"]
        held = {
            str(h["household_id"]) for h in listed if h["set"] == "featured" and h["archetype"] in HELD_OUT_ARCHETYPES
        }
    else:
        held = {h.household_id for h in read_manifest(book).households if h.archetype in HELD_OUT_ARCHETYPES}
    held |= {
        household
        for household, entry in load_ledger(ledger).households.items()
        if entry.archetype in HELD_OUT_ARCHETYPES and entry.pair == FEATURED_PAIR
    }
    return frozenset(held | private_households(ledger))


def reachable_households(task: Task, book: Path) -> frozenset[str]:
    """Every household whose files a run of the task can read: its own, or every one for a book-level task, and
    every one in the book for a task with the CRM sandbox's tools, since the sandbox holds every household's CRM
    (reviewers A and B, slice 12 round 1)."""
    if task.household_id == BOOK or any(t in CRM_TOOLS for t in task.allowed_tools):
        return frozenset(h.household_id for h in read_manifest(book).households)
    return frozenset({task.household_id})


def held_out_fixtures(task: Task, book: Path) -> list[str]:
    """The held-out households a run of the task can reach."""
    return sorted(reachable_households(task, book) & held_out_households(book))


def freeze_problems(task: Task, book: Path, record: Path | None = None) -> list[str]:
    """Why the task may not run on these fixtures now: none for fixtures not held out; else no recorded freeze,
    or each skill, checklist or grader hash that differs from the record."""
    held = held_out_fixtures(task, book)
    if not held:
        return []
    return [f"task {task.task_id} reads held-out fixtures ({', '.join(held)}){p}" for p in drift(record)]


def drift(record: Path | None = None) -> list[str]:
    """How today's skills, checklist and graders differ from the recorded freeze: none when every hash matches."""
    record = record or archetypes.FREEZE_RECORD
    if not record.is_file():
        return [f" and no freeze is recorded ({record}): the owner runs `casebook freeze` first"]
    recorded: dict[str, str] = json.loads(record.read_text(encoding="utf-8")).get("hashes", {})
    now = current_hashes()
    problems = [f": {name} differs from the freeze" for name in sorted(now) if recorded.get(name) != now[name]]
    problems += [f": {name} is in the freeze but no longer exists" for name in sorted(set(recorded) - set(now))]
    return problems


class NotFrozenError(RunRefusedError):
    pass


def require_freeze(task: Task, book: Path) -> None:
    """Freeze before held-out runs (docs/SPEC.md, Rules)."""
    problems = freeze_problems(task, book)
    if problems:
        raise NotFrozenError("\n".join(problems))


class MoveInError(RuntimeError):
    pass


def _script_slot(path: Path) -> tuple[str, int, int, str]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return str(raw["household_id"]), int(raw["archetype"]), int(raw["pair"]), str(raw["role"])


def move_in(private: Path, repo: Path | None = None) -> list[str]:
    """Copy the held-out pairs' folders from `$CASEBOOK_PRIVATE/book/scripted/` into the repo's `book/scripted/`
    and add their households to the ID ledger, with their archetype, pair and role. Refused with no recorded
    freeze, for a script that is not a held-out featured pair's, or when a folder is already in the repo."""
    repo = repo or REPO
    if not archetypes.frozen():
        raise MoveInError(f"no freeze is recorded ({archetypes.FREEZE_RECORD}): the held-out pairs stay private")
    sources = [private / SCRIPTED / f"archetype-{a}" for a in HELD_OUT_ARCHETYPES]
    slots: list[tuple[str, int, int, str]] = []
    for source in sources:
        target = repo / SCRIPTED / source.name
        if not source.is_dir():
            raise MoveInError(f"{source} is missing")
        if target.exists():
            raise MoveInError(f"{target} is already in the repo")
        for script in sorted(p for p in source.rglob("*.toml") if not p.name.endswith(".notes.toml")):
            household, archetype, pair, role = _script_slot(script)
            if archetype not in HELD_OUT_ARCHETYPES or pair != FEATURED_PAIR or (archetype, pair) in PRIVATE_PAIRS:
                raise MoveInError(f"{script}: {household} is archetype {archetype}, pair {pair}, not a held-out pair")
            slots.append((household, archetype, pair, role))
    ledger_path = repo / "book" / "id_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    for household, archetype, pair, role in slots:
        entry = {"archetype": archetype, "pair": pair, "role": role}
        if ledger["households"].get(household, entry) != entry:
            raise MoveInError(f"{household} is in the ledger as {ledger['households'][household]}, not {entry}")
        ledger["households"][household] = entry
    for source in sources:
        shutil.copytree(source, repo / SCRIPTED / source.name)
    ledger_path.write_text(ledger_text(ledger), encoding="utf-8")
    return sorted(household for household, *_ in slots)


def _entries(entries: dict[str, dict[str, Any]], order: Iterable[str]) -> str:
    lines = [
        f"    {json.dumps(key)}: {{ "
        + ", ".join(f"{json.dumps(k)}: {json.dumps(v)}" for k, v in entries[key].items())
        + " }"
        for key in order
    ]
    return ",\n".join(lines)


def ledger_text(ledger: dict[str, Any]) -> str:
    """The ledger as the repo writes it: one entry a line, households in ID order, tasks as published."""
    return (
        "{\n"
        f'  "_about": {json.dumps(ledger["_about"])},\n'
        '  "households": {\n'
        + _entries(ledger["households"], sorted(ledger["households"]))
        + '\n  },\n  "tasks": {\n'
        + _entries(ledger["tasks"], ledger["tasks"])
        + "\n  }\n}\n"
    )
