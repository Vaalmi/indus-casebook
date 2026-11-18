"""Slice 13: `casebook pass` runs every task under every arm, three repeats each: 24 public and 8 private tasks,
288 runs. A quota stop pauses the pass; `--resume` skips every run that reached `completed` or later and starts the
rest, a failed slot's new run naming the failed one under "retries"; the pass refuses to start when a held-out or
private slot's freeze does not match.

Every run here is the stand-in CLI's, or a fast stand-in for `run_and_grade`; `$CASEBOOK_PRIVATE`, the freeze
record and the published folders are temporary. A small task set here comes with a matrix that places exactly its
tasks, as a pass requires."""

import dataclasses
import json
import re
import shutil
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

import casebook.model.archetypes
import casebook.runner.freeze as freeze
from casebook.cli import main
from casebook.graders import registry
from casebook.model.ledger import is_private_task_id
from casebook.publish.private_set import private_households
from casebook.runner import full_pass, session
from casebook.runner.config import ARMS, SharedConfig
from casebook.runner.full_pass import (
    INTERRUPTED,
    Folders,
    PassRefusedError,
    load_pass,
    new_pass,
    run_pass,
    schedule,
)
from casebook.runner.preflight import FutureEvidenceError
from casebook.runner.record import HASH_FIELDS, RECORD_FIELDS, RunRecordError, check_record
from casebook.runner.run import GradeRefusedError, private_root
from casebook.site.results import results
from casebook.site.tasks import load_records
from casebook.tasks.matrix import load_matrix

from .conftest import ROOT, StandIn
from .test_freeze import all_pass
from .test_run_session import answer_for

TASKS = ROOT / "tasks" / "public"
# The private set's eight IDs, two per workflow, built so that no public file states one.
PRIVATE_IDS = tuple(f"X-{workflow}-{n:02d}" for workflow in ("REC", "MTG", "TAX", "CMP") for n in (1, 2))


def matrix_text(entries: Sequence[dict[str, str]]) -> str:
    """A task matrix placing exactly these tasks."""
    if not entries:
        return "tasks = []\n"
    return "".join("\n[[tasks]]\n" + "".join(f"{k} = {json.dumps(v)}\n" for k, v in e.items()) for e in entries)


def private_tasks(folder: Path, ids: tuple[str, ...] = PRIVATE_IDS, household: str = "HH-4821") -> Path:
    """Private task files: T-REC-01's under private IDs, beside a private matrix that places exactly them."""
    folder.mkdir(parents=True, exist_ok=True)
    text = (TASKS / "T-REC-01.toml").read_text().replace('household_id = "HH-4821"', f'household_id = "{household}"')
    for task_id in ids:
        (folder / f"{task_id}.toml").write_text(text.replace('task_id = "T-REC-01"', f'task_id = "{task_id}"'))
    placed = [{"task_id": t, "workflow": "reconciliation", "role": "book", "asks": "?"} for t in ids]
    (folder / "matrix.toml").write_text(matrix_text(placed))
    return folder


def public_tasks(folder: Path, *ids: str) -> Path:
    """Public task files, with the public matrix's places for them beside the folder, where a pass reads it."""
    folder.mkdir(parents=True)
    for task_id in ids:
        shutil.copy(TASKS / f"{task_id}.toml", folder)
    placements = [vars(p) for p in load_matrix(TASKS.parent / "matrix.toml").placements if p.task_id in ids]
    entries = [{k: str(v) for k, v in p.items() if v is not None} for p in placements]
    (folder.parent / "matrix.toml").write_text(matrix_text(entries))
    return folder


@pytest.fixture
def freeze_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Where the freeze is recorded, for this test: a temporary file, absent until a test records it."""
    path = tmp_path / "published" / "freeze.json"
    monkeypatch.setattr(casebook.model.archetypes, "FREEZE_RECORD", path)
    return path


@pytest.fixture
def frozen(freeze_record: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A freeze recorded on today's bytes: the public book holds the held-out pairs, which book-level tasks read."""
    monkeypatch.setattr(freeze, "self_tests", all_pass)
    freeze.record_freeze()
    return freeze_record


def pass_args(tmp_path: Path, book: Path, tasks: Path = TASKS) -> list[str]:
    return [
        *("pass", "--tasks", str(tasks), "--book", str(book), "--private-book", str(book)),
        *("--keys", str(tmp_path / "published" / "keys"), "--runs", str(tmp_path / "published" / "runs")),
    ]


def pass_id(out: str) -> str:
    found = re.search(r"pass (pass-\S+): state file", out)
    assert found, out
    return found.group(1)


def records(folder: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted(folder.rglob("*.json"))]


# The schedule.


def test_a_pass_schedules_288_runs_24_public_and_8_private_tasks_three_arms_three_repeats(
    tmp_path: Path, standin_cli: StandIn
) -> None:
    private = private_tasks(tmp_path / "private" / "tasks")
    folders = Folders(TASKS, private, tmp_path, tmp_path, tmp_path, tmp_path)
    task_ids = folders.task_ids()
    assert len(task_ids) == 32 and sum(map(is_private_task_id, task_ids)) == 8
    # The repo's public matrix and task files, and a private set of eight: the pass new_pass makes.
    slots = [s.slot for s in new_pass(folders, 3, SharedConfig()).slots]
    assert len(slots) == 288 and len(set(slots)) == 288
    assert Counter(s.arm for s in slots) == {"basic": 96, "checklist": 96, "skill": 96}
    assert Counter(s.repeat for s in slots) == {1: 96, 2: 96, 3: 96}
    assert all(n == 9 for n in Counter(s.task_id for s in slots).values())
    # The arms side by side: a stop anywhere leaves no arm more than one run behind another on a task.
    assert [(s.task_id, s.arm) for s in slots[:6]] == [
        ("T-CMP-01", "basic"),
        ("T-CMP-01", "checklist"),
        ("T-CMP-01", "skill"),
        ("T-CMP-02", "basic"),
        ("T-CMP-02", "checklist"),
        ("T-CMP-02", "skill"),
    ]
    assert all(s.repeat == 1 for s in slots[:96]) and slots[96].repeat == 2
    assert schedule(task_ids) == slots  # a fixed order, so a resume finds each slot where it was


# The inventory: a pass is of exactly the matrices' tasks (reviewers A and B, slice 13 round 1).


def test_a_pass_without_the_private_task_folder_is_refused_not_shrunk_to_216_runs(
    tmp_path: Path, standin_cli: StandIn
) -> None:
    """Reviewers A and B, slice 13 round 1: the repo's public tasks and a private task folder that does not exist
    made a pass of 216 slots, with no refusal; the private set was never run."""
    missing = tmp_path / "private" / "tasks"
    with pytest.raises(PassRefusedError, match=re.escape(f"the private task folder {missing} does not exist")):
        new_pass(Folders(TASKS, missing, tmp_path, tmp_path, tmp_path, tmp_path), 3, SharedConfig())


def test_a_pass_whose_tasks_are_not_the_matrices_tasks_is_refused(tmp_path: Path, standin_cli: StandIn) -> None:
    """Reviewers A and B, slice 13 round 1: each task the matrices place has its file, and no other is there."""
    private = private_tasks(tmp_path / "private" / "tasks")
    folders = Folders(TASKS, private, tmp_path, tmp_path, tmp_path, tmp_path)
    matrix = private / "matrix.toml"
    text = matrix.read_text()
    matrix.unlink()
    with pytest.raises(PassRefusedError, match=re.escape(f"the private task matrix {matrix} does not exist")):
        new_pass(folders, 3, SharedConfig())
    matrix.write_text(text)
    (private / f"{PRIVATE_IDS[0]}.toml").unlink()
    (private / ("X-" + "REC-09.toml")).write_text((private / f"{PRIVATE_IDS[1]}.toml").read_text())
    with pytest.raises(PassRefusedError) as refused:
        new_pass(folders, 3, SharedConfig())
    assert str(refused.value).splitlines()[1:] == [
        f"task {PRIVATE_IDS[0]} is in {matrix} but has no file in {private}",
        f"{private / ('X-' + 'REC-09')}.toml is not a task in {matrix}",
    ]
    # A public task missing from the repo's folder, against the repo's matrix of 24.
    public = tmp_path / "public"
    shutil.copytree(TASKS, public)
    shutil.copy(TASKS.parent / "matrix.toml", tmp_path / "matrix.toml")
    (public / "T-CMP-06.toml").unlink()
    (private / ("X-" + "REC-09.toml")).unlink()
    private_tasks(private)
    with pytest.raises(PassRefusedError, match=re.escape("task T-CMP-06 is in ")):
        new_pass(Folders(public, private, tmp_path, tmp_path, tmp_path, tmp_path), 3, SharedConfig())


# The plan's test: a quota stop at run 100, then a resume to 288 runs, no slot run twice once done.


def fast_runs(quota_at: int, seen: Callable[[int], None] = lambda _: None) -> tuple[list[str], Callable[..., Any]]:
    """A stand-in for `run_and_grade` that writes each run's records where it does, graded (mapped when public),
    and reports a quota stop on the `quota_at`th run."""
    calls: list[str] = []

    def run(
        task_id: str,
        arm: str,
        tasks: Path,
        book: Path,
        keys: Path,
        published: Path,
        config: SharedConfig,
        retries: Sequence[dict[str, str]] = (),
        run_id: str | None = None,
        slot: dict[str, str | int] | None = None,
    ) -> Any:
        calls.append(f"{task_id} {arm}")
        seen(len(calls))
        failed = len(calls) == quota_at
        assert run_id is not None and slot is not None  # a pass names each run, and its slot, before it starts
        record: dict[str, Any] = dict.fromkeys(RECORD_FIELDS) | {
            "run_id": run_id,
            "task_id": task_id,
            "arm": arm,
            "state": "failed" if failed else "graded",
            "failure_reason": "quota" if failed else None,
            "hashes": dict.fromkeys(HASH_FIELDS, "0" * 64),
            "attempts": [{"attempt": 1}],
            "grade": None if failed else {"score": 100, "passed": True},
            # Named as a real run is, so the private outcome counts written after the pass can be published.
            "cli_version": "2.1.304 (stand-in)",
            "models_reported": ["claude-opus-5-5"],
            "started_utc": f"2026-11-17T00:{len(calls) // 60:02d}:{len(calls) % 60:02d}+00:00",
            "settings": {"effort": "high"},
            **({"retries": list(retries)} if retries else {}),
            "slot": slot,
        }
        folder = private_root() / "runs" / run_id
        folder.mkdir(parents=True)
        (folder / "record.json").write_text(json.dumps(record))
        if is_private_task_id(task_id):
            return record
        public = record | {"state": "failed" if failed else "mapped"}
        (published / task_id).mkdir(parents=True, exist_ok=True)
        (published / task_id / f"{run_id}.json").write_text(json.dumps(public))
        return public

    return calls, run


def test_a_quota_stop_at_run_100_pauses_the_pass_and_resume_ends_with_288_records_and_no_duplicate(
    tmp_path: Path,
    real_book: Path,
    standin_cli: StandIn,
    frozen: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_tasks(private_root() / "tasks")
    saved_before: list[list[str]] = []

    def at_run(number: int) -> None:
        # The state file is written before and after every run: at run 50, the 49 before it are there, and the
        # 50th is named as running.
        if number == 50:
            [state] = (private_root() / "passes").glob("*/pass.json")
            saved_before.append([s["state"] for s in json.loads(state.read_text())["slots"]][:51])

    calls, run = fast_runs(quota_at=100, seen=at_run)
    monkeypatch.setattr(full_pass, "run_and_grade", run)
    assert main(pass_args(tmp_path, real_book)) == 1
    the_pass = pass_id(capsys.readouterr().out)
    [at_50] = saved_before
    assert all(state in ("graded", "mapped") for state in at_50[:49]) and at_50[49:] == ["running", "ready"]
    paused = load_pass(the_pass)
    assert paused.file.is_relative_to(private_root()) and not paused.file.is_relative_to(ROOT)
    assert paused.state == "paused" and len(paused.slots) == 288
    states = [s.state for s in paused.slots]
    assert states[:99] == ["mapped" if s.slot.task_id.startswith("T-") else "graded" for s in paused.slots[:99]]
    assert {"graded", "mapped"} <= set(states[:99])  # earlier runs graded, public and private
    assert states[99] == "failed" and paused.slots[99].runs[0].failure_reason == "quota"
    assert states[100:] == ["ready"] * 188

    assert main(["pass", "--resume", the_pass]) == 0
    done = load_pass(the_pass)
    assert done.state == "complete" and all(s.state in ("graded", "mapped") for s in done.slots)
    # 289 runs: each slot once, and slot 100 a second time, as a retry of its quota stop.
    assert len(calls) == 289 and sorted(Counter(calls).values()) == [3] * 95 + [4]
    finished = [r for r in records(private_root() / "runs") if r["state"] != "failed"]
    assert len(finished) == 288
    assert len({(s.slot, s.runs[-1].run_id) for s in done.slots}) == 288
    assert {r["run_id"] for r in finished} == {s.runs[-1].run_id for s in done.slots}
    retried = done.slots[99]
    [first, again] = retried.runs
    assert (first.state, again.state) == ("failed", retried.state)
    published = json.loads(
        (tmp_path / "published" / "runs" / retried.slot.task_id / f"{again.run_id}.json").read_text()
    )
    assert published["retries"] == [{"run_id": first.run_id, "failure_reason": "quota"}]
    # The private runs publish nothing: the published folder holds the public task's records only.
    assert not any(is_private_task_id(p.parent.name) for p in (tmp_path / "published" / "runs").rglob("*.json"))


# The same on the stand-in CLI and the real `run_and_grade`, at a size a check can afford.


def test_on_the_stand_in_a_quota_stop_pauses_and_resume_runs_each_slot_once(
    tmp_path: Path, real_book: Path, standin_cli: StandIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    standin_cli.answer.write_text(answer_for(real_book))
    private_id = "X-" + "REC-09"
    private_tasks(private_root() / "tasks", (private_id,))
    tasks = public_tasks(tmp_path / "tasks", "T-REC-01")
    real_run = full_pass.run_and_grade
    calls: list[str] = []

    def quota_on_the_third(*args: Any, **named: Any) -> Any:
        calls.append(f"{args[0]} {args[1]}")
        standin_cli.set("quota" if len(calls) == 3 else "answer")
        return real_run(*args, **named)

    monkeypatch.setattr(full_pass, "run_and_grade", quota_on_the_third)
    folders = Folders(
        tasks, private_root() / "tasks", real_book, real_book, tmp_path / "keys", tmp_path / "published" / "runs"
    )
    paused = run_pass(new_pass(folders, 1, SharedConfig()))
    assert paused.state == "paused"
    assert [s.state for s in paused.slots] == ["mapped", "mapped", "failed", "ready", "ready", "ready"]
    assert paused.slots[2].runs[0].failure_reason == "quota"

    done = run_pass(load_pass(paused.pass_id))
    assert done.state == "complete"
    assert [s.state for s in done.slots] == ["mapped"] * 3 + ["graded"] * 3
    assert calls == [f"T-REC-01 {arm}" for arm in ARMS] + ["T-REC-01 skill"] + [f"{private_id} {arm}" for arm in ARMS]
    assert len(standin_cli.log.read_text().splitlines()) == 7
    # Published: the three public runs and the quota stop, kept; the retry names it.
    published = {r["run_id"]: r for r in records(tmp_path / "published" / "runs")}
    quota, retry = done.slots[2].runs
    assert set(published) == {s.runs[-1].run_id for s in done.slots[:3]} | {quota.run_id}
    assert published[quota.run_id]["state"] == "failed" and "retries" not in published[quota.run_id]
    assert published[retry.run_id]["retries"] == [{"run_id": quota.run_id, "failure_reason": "quota"}]
    private = json.loads((private_root() / "runs" / retry.run_id / "record.json").read_text())
    assert private["retries"] == [{"run_id": quota.run_id, "failure_reason": "quota"}]
    # The private task's runs stay in $CASEBOOK_PRIVATE, graded.
    for slot in done.slots[3:]:
        record = json.loads((private_root() / "runs" / slot.runs[0].run_id / "record.json").read_text())
        assert record["task_id"] == private_id and record["state"] == "graded" and record["grade"]["score"] == 100


def test_a_failed_run_is_listed_with_its_reason_and_resumed_as_a_retry_naming_it(
    tmp_path: Path,
    real_book: Path,
    standin_cli: StandIn,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    standin_cli.answer.write_text(answer_for(real_book))
    tasks = public_tasks(tmp_path / "tasks", "T-REC-01")
    real_run = full_pass.run_and_grade
    calls: list[str] = []

    def error_on_the_second(*args: Any, **named: Any) -> Any:
        calls.append(f"{args[0]} {args[1]}")
        standin_cli.set("error" if len(calls) == 2 else "answer")
        return real_run(*args, **named)

    private_tasks(private_root() / "tasks", ())
    monkeypatch.setattr(full_pass, "run_and_grade", error_on_the_second)
    folders = Folders(
        tasks, private_root() / "tasks", real_book, real_book, tmp_path / "keys", tmp_path / "published" / "runs"
    )
    # One attempt per run, so the failure is quick; the pass keeps this configuration when it resumes.
    ended = run_pass(new_pass(folders, 1, SharedConfig(retries=0)))
    # Not a quota stop: the pass goes on, and ends complete with the failed slot listed.
    assert ended.state == "complete" and [s.state for s in ended.slots] == ["mapped", "failed", "mapped"]
    [failed] = ended.slots[1].runs
    reason = "CLI error (exit code 1): API Error: overloaded"
    assert failed.failure_reason == reason

    assert main(["pass", "--status", ended.pass_id]) == 0
    status = capsys.readouterr().out
    assert f"pass {ended.pass_id}: complete, 3 slots: 1 failed, 2 mapped" in status
    assert f"  T-REC-01 checklist repeat 1: {failed.run_id}: {reason}" in status

    assert main(["pass", "--resume", ended.pass_id]) == 0
    assert calls == ["T-REC-01 basic", "T-REC-01 checklist", "T-REC-01 skill", "T-REC-01 checklist"]
    done = load_pass(ended.pass_id)
    assert done.config == SharedConfig(retries=0)
    retry = done.slots[1].runs[-1]
    published = json.loads((tmp_path / "published" / "runs" / "T-REC-01" / f"{retry.run_id}.json").read_text())
    assert published["state"] == "mapped" and published["retries"] == [
        {"run_id": failed.run_id, "failure_reason": reason}
    ]
    assert "(retried; the slot is now mapped)" in capsys.readouterr().out


# Refused before the first run.


def test_a_pass_is_refused_before_its_first_run_when_a_held_out_or_private_slot_s_freeze_does_not_match(
    tmp_path: Path,
    real_book: Path,
    standin_cli: StandIn,
    freeze_record: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The real-ticker build with HH-7350 listed as archetype 8's featured twin: T-REC-02 reads held-out fixtures.
    book = tmp_path / "held-out-book"
    shutil.copytree(real_book, book)
    sealed = book / "sealed" / "households.json"
    data = json.loads(sealed.read_text())
    next(h for h in data["households"] if h["household_id"] == "HH-7350")["archetype"] = 8
    sealed.write_text(json.dumps(data))
    private_id = "X-" + "REC-09"
    household = sorted(private_households())[0]
    private_tasks(private_root() / "tasks", (private_id,), household)
    tasks = public_tasks(tmp_path / "tasks", "T-REC-01", "T-REC-02")

    assert main(pass_args(tmp_path, book, tasks)) == 2
    err = capsys.readouterr().err
    assert "PassRefusedError: pass pass-" in err and "refused before starting a run" in err
    assert "task T-REC-02 reads held-out fixtures (HH-7350) and no freeze is recorded" in err
    assert f"task {private_id} reads held-out fixtures ({household}) and no freeze is recorded" in err
    assert "T-REC-01" not in err
    # Nothing ran and nothing was written: no state file, no key, no record.
    assert not standin_cli.log.exists()
    assert not (private_root() / "passes").exists() and not (tmp_path / "published").exists()


def test_a_resume_under_another_freeze_is_refused(
    tmp_path: Path,
    real_book: Path,
    standin_cli: StandIn,
    freeze_record: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A task page refuses arms from two freezes, so one pass never spans two."""
    calls, run = fast_runs(quota_at=2)
    monkeypatch.setattr(full_pass, "run_and_grade", run)
    tasks = public_tasks(tmp_path / "tasks", "T-REC-01")
    private_tasks(private_root() / "tasks", ())
    assert main(pass_args(tmp_path, real_book, tasks)) == 1
    the_pass = pass_id(capsys.readouterr().out)
    monkeypatch.setattr(freeze, "self_tests", all_pass)
    freeze.record_freeze()
    assert main(["pass", "--resume", the_pass]) == 2
    assert f"the freeze changed since pass {the_pass} started (None then, " in capsys.readouterr().err
    assert len(calls) == 2 and load_pass(the_pass).state == "paused"


def test_an_unknown_pass_is_refused(standin_cli: StandIn, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["pass", "--status", "pass-20261117T000000Z-0000"]) == 2
    assert "no pass pass-20261117T000000Z-0000" in capsys.readouterr().err
    assert main(["pass", "--resume", "../../elsewhere"]) == 2
    assert "is not a pass ID" in capsys.readouterr().err


def test_a_run_record_s_retries_name_each_earlier_run_and_why_it_failed() -> None:
    record: dict[str, Any] = dict.fromkeys(RECORD_FIELDS) | {
        "run_id": "T-REC-01-basic-2",
        "state": "completed",
        "hashes": dict.fromkeys(HASH_FIELDS, "0" * 64),
    }
    assert check_record(record) == record  # a first run has none
    check_record(record | {"retries": [{"run_id": "T-REC-01-basic-1", "failure_reason": "quota"}]})
    for retries in ([{"run_id": "T-REC-01-basic-1"}], [{"run_id": "T-REC-01-basic-1", "failure_reason": None}]):
        with pytest.raises(RunRecordError, match="each retry names an earlier run and why it failed"):
            check_record(record | {"retries": retries})


def test_a_run_record_s_slot_names_its_pass_and_repeat() -> None:
    """Reviewers A and B, slice 13 round 1: a pass's run is known by its slot from the moment it starts."""
    record: dict[str, Any] = dict.fromkeys(RECORD_FIELDS) | {
        "run_id": "T-REC-01-basic-1",
        "state": "completed",
        "hashes": dict.fromkeys(HASH_FIELDS, "0" * 64),
    }
    check_record(record | {"slot": {"pass_id": "pass-20261117T000000Z-0000", "repeat": 2}})
    for slot in (
        {"pass_id": "pass-20261117T000000Z-0000"},
        {"pass_id": " ", "repeat": 1},
        {"pass_id": "pass-20261117T000000Z-0000", "repeat": 0},
        {"pass_id": "pass-20261117T000000Z-0000", "repeat": "1"},
        None,
    ):
        with pytest.raises(RunRecordError, match="its slot names a pass and a repeat from 1"):
            check_record(record | {"slot": slot})


# A stop between a run and the pass's state file (reviewers A and B, slice 13 round 1).


class Stopped(BaseException):
    """The pass's process stopping: a kill, a crash, a closed terminal."""


def interrupted_pass(
    tmp_path: Path, real_book: Path, standin_cli: StandIn, monkeypatch: pytest.MonkeyPatch, stop: str, mode: str
) -> tuple[Path, Path, Any, list[str]]:
    """A one-repeat pass of T-REC-01 whose process stops in its second run (the checklist's), at `stop`: before
    the run (no record), after its record is written as completed (before grading), or after it is published."""
    standin_cli.answer.write_text(answer_for(real_book))
    tasks = public_tasks(tmp_path / "tasks", "T-REC-01")
    private_tasks(private_root() / "tasks", ())
    published = tmp_path / "published" / "runs"
    real_run, real_finish = full_pass.run_and_grade, session.finish_run
    started: list[str] = []

    def stops_in_the_second(*args: Any, **named: Any) -> Any:
        started.append(named["run_id"])
        standin_cli.set(mode if len(started) == 2 else "answer")
        if len(started) == 2 and stop == "before the run":
            raise Stopped
        record = real_run(*args, **named)
        if len(started) == 2 and stop == "after publishing":
            raise Stopped  # the run's records are written; the pass's state file is not yet
        return record

    def stops_before_grading(*args: Any, **named: Any) -> Any:
        if len(started) == 2 and stop == "before grading" and not getattr(stops_before_grading, "done", False):
            stops_before_grading.done = True  # type: ignore[attr-defined]
            raise Stopped  # the record is written as completed; grading, mapping and publishing have not begun
        return real_finish(*args, **named)

    monkeypatch.setattr(full_pass, "run_and_grade", stops_in_the_second)
    monkeypatch.setattr(session, "finish_run", stops_before_grading)
    folders = Folders(tasks, private_root() / "tasks", real_book, real_book, tmp_path / "keys", published)
    the_pass = new_pass(folders, 1, SharedConfig(retries=0))
    with pytest.raises(Stopped):
        run_pass(the_pass)
    stopped = load_pass(the_pass.pass_id)
    assert [s.state for s in stopped.slots] == ["mapped", "running", "ready"]
    assert stopped.slots[1].runs[0].run_id == started[1]
    return tasks, published, the_pass, started


@pytest.mark.parametrize("stop", ["after publishing", "before grading"])
def test_a_run_interrupted_after_its_record_was_written_is_kept_not_run_again(
    stop: str, tmp_path: Path, real_book: Path, standin_cli: StandIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reviewers A and B, slice 13 round 2: a run interrupted after it completed was closed as failed and run
    again, throwing away its outcome and spending another live run. Now the resume reads its record: published,
    it is kept; completed but not yet graded, it is graded, mapped and published now; its slot is done."""
    _, published, the_pass, started = interrupted_pass(tmp_path, real_book, standin_cli, monkeypatch, stop, "answer")
    interrupted = started[1]
    if stop == "before grading":
        record = json.loads((private_root() / "runs" / interrupted / "record.json").read_text())
        assert record["state"] == "completed" and not (published / "T-REC-01" / f"{interrupted}.json").exists()
    assert main(["pass", "--resume", the_pass.pass_id]) == 0
    # Three launches: the interrupted run is not launched again.
    assert [run_id.split("-")[3] for run_id in started] == ["basic", "checklist", "skill"]
    done = load_pass(the_pass.pass_id)
    assert [s.state for s in done.slots] == ["mapped"] * 3
    [kept] = done.slots[1].runs
    assert (kept.run_id, kept.state) == (interrupted, "mapped") and not done.failed_runs()
    public = json.loads((published / "T-REC-01" / f"{interrupted}.json").read_text())
    assert public["state"] == "mapped" and public["grade"]["passed"] and "retries" not in public
    assert len(list((published / "T-REC-01").glob("*[0-9a-f].json"))) == 3


@pytest.mark.parametrize(("stop", "mode"), [("before the run", "answer"), ("after publishing", "error")])
def test_a_run_interrupted_with_no_record_or_failed_runs_again_naming_it(
    stop: str,
    mode: str,
    tmp_path: Path,
    real_book: Path,
    standin_cli: StandIn,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reviewers A and B, slice 13 round 1: an interrupted run's slot ran again with empty `retries`. A run that
    never wrote its record is closed as interrupted; one that failed keeps its own reason; either way its slot runs
    again, the new run naming it under `retries`, and the results page counts the slot once."""
    tasks, published, the_pass, started = interrupted_pass(tmp_path, real_book, standin_cli, monkeypatch, stop, mode)
    interrupted = started[1]
    assert main(["pass", "--resume", the_pass.pass_id]) == 0
    assert [run_id.split("-")[3] for run_id in started] == ["basic", "checklist", "checklist", "skill"]
    done = load_pass(the_pass.pass_id)
    assert [s.state for s in done.slots] == ["mapped"] * 3
    closed, retry = done.slots[1].runs
    reason = INTERRUPTED if stop == "before the run" else closed.failure_reason
    assert (closed.run_id, closed.state) == (interrupted, "failed") and closed.failure_reason == reason
    if stop == "before the run":
        assert INTERRUPTED == "interrupted before the pass recorded it"
    else:
        assert reason and reason.startswith("CLI error")
    again = json.loads((published / "T-REC-01" / f"{retry.run_id}.json").read_text())
    assert again["retries"] == [{"run_id": interrupted, "failure_reason": reason}]
    capsys.readouterr()
    assert main(["pass", "--status", the_pass.pass_id]) == 0
    status = capsys.readouterr().out
    assert "failed runs: 1" in status and f"T-REC-01 checklist repeat 1: {interrupted}: {reason}" in status
    [section] = results(load_records(published), tasks, ())
    assert section.public["reconciliation"]["checklist"] == {"passed": 1, "failed": 0, "failed_run": 0, "held": 0}


def test_the_private_counts_are_written_from_the_private_task_folder_the_pass_ran_with(
    tmp_path: Path,
    real_book: Path,
    standin_cli: StandIn,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reviewer B, slice 13 round 1: with `--private-tasks` naming another folder, the pass ran its tasks and then
    failed writing the summary, which looked for them in `$CASEBOOK_PRIVATE/tasks`."""
    private_id = "X-" + "REC-09"
    elsewhere = private_tasks(private_root() / "alternate-tasks", (private_id,))
    assert not (private_root() / "tasks").exists()
    tasks = public_tasks(tmp_path / "tasks", "T-REC-01")
    calls, run = fast_runs(quota_at=0)  # no quota stop
    monkeypatch.setattr(full_pass, "run_and_grade", run)
    args = [*pass_args(tmp_path, real_book, tasks), "--private-tasks", str(elsewhere), "--repeats", "1"]
    assert main(args) == 0
    assert len(calls) == 6
    summary = tmp_path / "published" / "results" / "private-outcomes.json"
    assert f"private outcome counts: {summary}" in capsys.readouterr().out
    [run_set] = json.loads(summary.read_text())["run_sets"]
    passed_once = {"passed": 1, "failed": 0, "failed_run": 0, "held": 0}
    assert run_set["counts"]["reconciliation"] == dict.fromkeys(ARMS, passed_once)


def test_a_completed_run_whose_key_changed_is_kept_ungraded_not_graded_against_another_key(
    tmp_path: Path,
    real_book: Path,
    standin_cli: StandIn,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reviewers A and B, slice 13 targeted check: recovery graded a completed run against a key computed from
    the book as it is now, not the key the run had, and turned a refused grade into a rerun. The key computed now
    must hash as the run's recorded answer key; otherwise the run is kept, completed and ungraded, listed, and its
    slot is not run again."""
    _, published, the_pass, started = interrupted_pass(
        tmp_path, real_book, standin_cli, monkeypatch, "before grading", "answer"
    )
    interrupted = started[1]
    spec = registry.GRADERS["fee_reconciliation"]

    def another_household_s_key(book: Path, household: str, params: dict[str, Any]) -> Any:
        return spec.key(book, "HH-7350", params)  # a key the run did not have

    another = dataclasses.replace(spec, key=another_household_s_key)
    monkeypatch.setitem(registry.GRADERS, "fee_reconciliation", another)
    # The pass completes, and exits 1: a run it has is not graded (second targeted check).
    assert main(["pass", "--resume", the_pass.pass_id]) == 1
    assert [run_id.split("-")[3] for run_id in started] == ["basic", "checklist", "skill"]
    done = load_pass(the_pass.pass_id)
    assert [s.state for s in done.slots] == ["mapped", "completed", "mapped"]
    [kept] = done.slots[1].runs
    assert kept.run_id == interrupted and kept.state == "completed"
    assert kept.failure_reason and "the answer key computed now is not the one it ran with" in kept.failure_reason
    assert not (published / "T-REC-01" / f"{interrupted}.json").exists()
    capsys.readouterr()
    main(["pass", "--status", the_pass.pass_id])
    status = capsys.readouterr().out
    assert "completed runs not graded: 1" in status and interrupted in status


def test_a_run_whose_transcript_was_not_yet_published_is_published_whole_on_resume(
    tmp_path: Path, real_book: Path, standin_cli: StandIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reviewer A, slice 13 targeted check: a stop between the published record and its transcript left the slot
    done with no transcript. Recovery publishes the run again, record and transcript."""
    _, published, the_pass, started = interrupted_pass(
        tmp_path, real_book, standin_cli, monkeypatch, "after publishing", "answer"
    )
    interrupted = started[1]
    transcript = published / "T-REC-01" / f"{interrupted}.transcript.jsonl"
    transcript.unlink()  # the stop came after the record and before the transcript
    assert main(["pass", "--resume", the_pass.pass_id]) == 0
    assert [run_id.split("-")[3] for run_id in started] == ["basic", "checklist", "skill"]
    assert transcript.is_file() and transcript.read_text().strip()


def test_a_private_run_kept_ungraded_holds_back_the_private_counts_and_fails_the_pass_without_a_rerun(
    tmp_path: Path,
    real_book: Path,
    standin_cli: StandIn,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reviewers A and B, slice 13 second targeted check: a private run a resume kept completed and ungraded (its
    grade refused) reached the private summary, whose `outcome` raised an uncaught ResultsError, on this resume
    and every later one. Now the pass completes without running the slot again, writes no private counts, says
    why, lists the run, and exits 1."""
    private_id = "X-" + "REC-09"
    private = private_tasks(private_root() / "tasks", (private_id,))
    tasks = public_tasks(tmp_path / "tasks", "T-REC-01")
    calls, fast = fast_runs(quota_at=0)

    def stops_in_the_private_checklist(*args: Any, **named: Any) -> Any:
        record = fast(*args, **named)
        if record["task_id"] == private_id and record["arm"] == "checklist":
            file = private_root() / "runs" / record["run_id"] / "record.json"
            file.write_text(json.dumps(record | {"state": "completed", "grade": None}))
            raise Stopped  # the run completed; its grading had not begun
        return record

    def refused(*_: Any) -> Any:
        raise GradeRefusedError("the answer key computed now is not the one it ran with")

    monkeypatch.setattr(full_pass, "run_and_grade", stops_in_the_private_checklist)
    folders = Folders(tasks, private, real_book, real_book, tmp_path / "keys", tmp_path / "published" / "runs")
    the_pass = new_pass(folders, 1, SharedConfig(retries=0))
    with pytest.raises(Stopped):
        run_pass(the_pass)
    monkeypatch.setattr(full_pass, "recover_run", refused)
    capsys.readouterr()
    assert main(["pass", "--resume", the_pass.pass_id]) == 1
    assert len(calls) == 6  # the kept run's slot is not run again
    done = load_pass(the_pass.pass_id)
    assert done.state == "complete" and sum(s.state == "completed" for s in done.slots) == 1
    out, err = capsys.readouterr()
    assert "completed runs not graded: 1" in out
    assert "private outcome counts not written" in err and "completed with no grade" in err
    assert not (tmp_path / "published" / "results" / "private-outcomes.json").exists()
    # Every later resume says the same, and runs nothing.
    assert main(["pass", "--resume", the_pass.pass_id]) == 1 and len(calls) == 6


def test_a_run_refused_before_its_cli_started_leaves_its_slot_as_it_was(
    tmp_path: Path, real_book: Path, standin_cli: StandIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The live pass, 18 November 2026: a preflight refusal (T-CMP-06's) left its run "running" in the state
    file, for a resume to close as a failed, interrupted run though no CLI had started. Now the refused run is
    taken back out, the slot is as it was, and a resume runs it once, with no failure listed."""
    tasks = public_tasks(tmp_path / "tasks", "T-REC-01")
    private_tasks(private_root() / "tasks", ())
    calls, fast = fast_runs(quota_at=0)
    refuse = [True]

    def refused_second(*args: Any, **named: Any) -> Any:
        if len(calls) == 1 and refuse[0]:
            refuse[0] = False
            raise FutureEvidenceError("households/HH-0120/documents/x.pdf is not in the document index")
        return fast(*args, **named)

    monkeypatch.setattr(full_pass, "run_and_grade", refused_second)
    folders = Folders(
        tasks, private_root() / "tasks", real_book, real_book, tmp_path / "keys", tmp_path / "published" / "runs"
    )
    the_pass = new_pass(folders, 1, SharedConfig(retries=0))
    with pytest.raises(FutureEvidenceError):
        run_pass(the_pass)
    stopped = load_pass(the_pass.pass_id)
    assert [s.state for s in stopped.slots] == ["mapped", "ready", "ready"] and stopped.slots[1].runs == []
    assert main(["pass", "--resume", the_pass.pass_id]) == 0
    done = load_pass(the_pass.pass_id)
    assert [s.state for s in done.slots] == ["mapped"] * 3 and not done.failed_runs()
    assert [len(s.runs) for s in done.slots] == [1, 1, 1] and len(calls) == 3
