"""`casebook pass`: every task under every arm, three repeats each, with pause and resume (docs/PLAN.md, slice 13).

A pass is a list of run slots, one per task, arm and repeat, run in a fixed order through `run_and_grade`. Its
state file, `$CASEBOOK_PRIVATE/passes/<pass id>/pass.json`, holds each slot's state (`ready`, then its last run's:
`running`, `failed`, `graded`, `mapped`), its runs and the one configuration the whole pass shares. It is written
before each run, naming the run as `running` under the ID it will have, and after it, so a stopped process loses no
run: one still `running` on resume is closed as failed, interrupted, and its slot runs again. A quota stop marks the
pass `paused`; resuming skips every slot whose run reached `completed` or a later state and starts the rest, a
failed slot's new run naming the failed ones under "retries" in its run record (docs/PLAN.md, the run's state
table).
"""

import json
import re
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from casebook.model.ledger import is_private_task_id
from casebook.runner.config import ARMS, SharedConfig
from casebook.runner.freeze import freeze_identity, freeze_problems
from casebook.runner.preflight import RunRefusedError
from casebook.runner.record import STATES
from casebook.runner.run import GradeRefusedError, new_run_id, private_root
from casebook.runner.session import recover_run, run_and_grade
from casebook.runner.transcript import QUOTA_REASON
from casebook.tasks.matrix import load_matrix
from casebook.tasks.task import TaskFormatError, find_task

REPEATS = 3
PASSES = Path("passes")
STATE_FILE = "pass.json"
READY = "ready"
# A run the pass has started and not yet recorded the end of.
RUNNING = "running"
# Why a run the pass started is closed on resume: the process stopped before the pass recorded how it ended.
INTERRUPTED = "interrupted before the pass recorded it"
# A completed run a resume could not grade (its task, key or grader changed since): kept, listed, not run again.
NOT_GRADED = "completed, not graded"
# A slot whose run reached any of these is never run again (docs/PLAN.md: "skips every run that reached
# `completed` or any state after it").
DONE = ("completed", "graded", "mapped", "published")
SLOT_STATES = (READY, RUNNING, *STATES)
PASS_STATES = ("running", "paused", "complete")
PASS_ID = re.compile(r"pass-\d{8}T\d{6}Z-[0-9a-f]{4}")
# The task matrices: the public one beside the public task folder (`tasks/matrix.toml`), the private one in the
# private task folder (`$CASEBOOK_PRIVATE/tasks/matrix.toml`).
MATRIX = "matrix.toml"
# A task file, public or private, by its name.
TASK_FILES = ("T-*.toml", "X-*.toml")


@dataclass(frozen=True)
class Slot:
    """One run a pass owes: a task under an arm, the nth time."""

    task_id: str
    arm: str
    repeat: int

    def __str__(self) -> str:
        return f"{self.task_id} {self.arm} repeat {self.repeat}"


def schedule(task_ids: Sequence[str], repeats: int = REPEATS) -> list[Slot]:
    """Repeat by repeat, task by task, the three arms side by side: a pass stopped anywhere leaves no arm more
    than one run behind another on a task, and every task's first repeat before any task's second."""
    return [Slot(task, arm, repeat) for repeat in range(1, repeats + 1) for task in task_ids for arm in ARMS]


@dataclass(frozen=True)
class Folders:
    """Where a pass reads its tasks and books and writes its keys and published records, as `casebook run`
    chooses them: public tasks on the public real-ticker build, private ones on the private build."""

    tasks: Path
    private_tasks: Path
    book: Path
    private_book: Path
    keys: Path
    runs: Path

    def task_ids(self) -> list[str]:
        public = [p.stem for p in sorted(self.tasks.glob("T-*.toml"))]
        return public + [p.stem for p in sorted(self.private_tasks.glob("*.toml")) if is_private_task_id(p.stem)]

    def matrices(self) -> tuple[tuple[Path, Path, bool], ...]:
        """Each task folder with its matrix, and whether its tasks are the private set's."""
        public = (self.tasks, self.tasks.parent / MATRIX, False)
        return (public, (self.private_tasks, self.private_tasks / MATRIX, True))

    def for_task(self, task_id: str) -> tuple[Path, Path]:
        """The task's folder and the book it runs on."""
        return (self.private_tasks, self.private_book) if is_private_task_id(task_id) else (self.tasks, self.book)


@dataclass(frozen=True)
class SlotRun:
    run_id: str
    state: str
    failure_reason: str | None
    attempts: int


@dataclass
class SlotState:
    slot: Slot
    state: str = READY
    runs: list[SlotRun] = field(default_factory=list[SlotRun])

    @property
    def done(self) -> bool:
        return self.state in DONE


class PassRefusedError(RunRefusedError):
    pass


@dataclass
class Pass:
    pass_id: str
    state: str
    repeats: int
    # The freeze the pass started under: one pass never spans two (a task page refuses arms from two freezes).
    freeze: str | None
    config: SharedConfig
    folders: Folders
    slots: list[SlotState]

    @property
    def file(self) -> Path:
        return pass_file(self.pass_id)

    def save(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.to_dict(), indent=2) + "\n"
        temporary = self.file.with_suffix(".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(self.file)

    def failed_runs(self) -> list[tuple[SlotState, SlotRun]]:
        """Every failed run of the pass, a retried slot's too."""
        return [(s, r) for s in self.slots for r in s.runs if r.state == "failed"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pass_id": self.pass_id,
            "state": self.state,
            "repeats": self.repeats,
            "freeze": self.freeze,
            "config": self.config.as_dict(),
            "folders": {name: str(path) for name, path in vars(self.folders).items()},
            "slots": [
                {
                    "task_id": s.slot.task_id,
                    "arm": s.slot.arm,
                    "repeat": s.slot.repeat,
                    "state": s.state,
                    "runs": [vars(r) for r in s.runs],
                }
                for s in self.slots
            ],
        }


def pass_file(pass_id: str) -> Path:
    if not PASS_ID.fullmatch(pass_id):
        raise PassRefusedError(f"{pass_id!r} is not a pass ID (pass-YYYYMMDDTHHMMSSZ-xxxx)")
    return private_root() / PASSES / pass_id / STATE_FILE


def inventory_problems(folders: Folders) -> list[str]:
    """Why the task files are not exactly the matrices' tasks: a folder or matrix missing, a matrix task with no
    file, a task file the matrix does not place, or a task in the wrong matrix. A pass of fewer tasks than the
    matrices place would finish without them (reviewers A and B, slice 13 round 1)."""
    problems: list[str] = []
    for folder, matrix, private in folders.matrices():
        which = "private" if private else "public"
        if not folder.is_dir():
            problems.append(f"the {which} task folder {folder} does not exist")
            continue
        if not matrix.is_file():
            problems.append(f"the {which} task matrix {matrix} does not exist")
            continue
        try:
            placed = {p.task_id for p in load_matrix(matrix).placements}
        except ValueError as error:  # a MatrixError, or TOML that does not parse
            problems.append(f"the {which} task matrix {matrix} cannot be read: {error}")
            continue
        files = {p.stem for pattern in TASK_FILES for p in folder.glob(pattern)}
        problems += [f"task {t} is in {matrix} but has no file in {folder}" for t in sorted(placed - files)]
        problems += [f"{folder / t}.toml is not a task in {matrix}" for t in sorted(files - placed)]
        problems += [
            f"task {t} in {matrix} is not a {which} task ID" for t in sorted(placed) if is_private_task_id(t) != private
        ]
    return problems


def new_pass(folders: Folders, repeats: int, config: SharedConfig) -> Pass:
    """A pass of every task the matrices place, not yet started or saved; refused unless each has its file and
    nothing else is there."""
    problems = inventory_problems(folders)
    if problems:
        raise PassRefusedError("the pass's tasks are not the matrices' tasks:\n" + "\n".join(problems))
    task_ids = folders.task_ids()
    pass_id = f"pass-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(2)}"
    slots = [SlotState(slot) for slot in schedule(task_ids, repeats)]
    absolute = Folders(**{name: path.resolve() for name, path in vars(folders).items()})
    return Pass(pass_id, "running", repeats, freeze_identity(), config, absolute, slots)


def load_pass(pass_id: str) -> Pass:
    path = pass_file(pass_id)
    if not path.is_file():
        raise PassRefusedError(f"no pass {pass_id} ({path} does not exist)")
    return parse_pass(json.loads(path.read_text(encoding="utf-8")))


def parse_pass(raw: dict[str, Any]) -> Pass:
    """The state file, checked: a state, arm or slot it does not know is refused, not run."""
    pass_id = str(raw["pass_id"])
    slots: list[SlotState] = []
    for entry in raw["slots"]:
        slot = Slot(str(entry["task_id"]), str(entry["arm"]), int(entry["repeat"]))
        if slot.arm not in ARMS or entry["state"] not in SLOT_STATES:
            raise PassRefusedError(f"pass {pass_id}: slot {slot} is {entry['state']!r} under an arm or state unknown")
        runs = [
            SlotRun(str(r["run_id"]), str(r["state"]), r["failure_reason"], int(r["attempts"])) for r in entry["runs"]
        ]
        slots.append(SlotState(slot, str(entry["state"]), runs))
    if raw["state"] not in PASS_STATES or len({s.slot for s in slots}) != len(slots):
        raise PassRefusedError(f"pass {pass_id}: state {raw['state']!r}, or a slot listed twice")
    # Tuples are stored as JSON lists; the config is rebuilt as it was, so every run of the pass shares it, and
    # one the code can no longer rebuild exactly is refused.
    stored: dict[str, Any] = {k: tuple(v) if isinstance(v, list) else v for k, v in raw["config"].items()}
    try:
        config = SharedConfig(**stored)
    except TypeError as error:
        raise PassRefusedError(f"pass {pass_id}: its shared configuration cannot be rebuilt: {error}") from error
    if config.as_dict() != raw["config"]:
        raise PassRefusedError(f"pass {pass_id}: its shared configuration no longer rebuilds exactly")
    folders = Folders(**{name: Path(path) for name, path in raw["folders"].items()})
    return Pass(pass_id, str(raw["state"]), int(raw["repeats"]), raw["freeze"], config, folders, slots)


def start_problems(run: Pass) -> list[str]:
    """Why the pass may not start: a task missing, the freeze changed since the pass started, or a held-out or
    private slot whose freeze does not match today's hashes (docs/SPEC.md, Rules: "Freeze before held-out runs")."""
    problems: list[str] = []
    now = freeze_identity()
    if now != run.freeze:
        problems.append(f"the freeze changed since pass {run.pass_id} started ({run.freeze} then, {now} now)")
    for task_id in dict.fromkeys(s.slot.task_id for s in run.slots if not s.done):
        tasks, book = run.folders.for_task(task_id)
        try:
            problems += freeze_problems(find_task(tasks, task_id), book)
        except TaskFormatError as error:
            problems.append(str(error))
    return problems


def close_interrupted(run: Pass) -> None:
    """Settle each run the pass started and never recorded the end of: the process stopped while it ran, or after
    it ended and before the state file was written. A run that wrote its record keeps it: one that completed is
    graded, mapped and published now, and its slot is done (reviewers A and B, slice 13 round 2: a completed
    outcome is never thrown away, nor a live run spent again); one that failed, or never wrote its record, is closed
    failed, and its slot runs again, the new run naming it under "retries"."""
    settled = False
    for slot_state in run.slots:
        last = slot_state.runs[-1] if slot_state.runs else None
        if last is None or last.state != RUNNING:
            continue
        tasks, book = run.folders.for_task(slot_state.slot.task_id)
        try:
            record = recover_run(slot_state.slot.task_id, tasks, book, run.folders.keys, run.folders.runs, last.run_id)
        except GradeRefusedError as error:
            # The run completed: it is kept, ungraded and listed, never run again (targeted check).
            slot_state.runs[-1] = SlotRun(last.run_id, "completed", f"{NOT_GRADED}: {error}", last.attempts)
            slot_state.state = "completed"
            settled = True
            continue
        if record is None:
            record = {"state": "failed", "failure_reason": INTERRUPTED}
        reason = record["failure_reason"] if record["state"] == "failed" else None
        slot_state.runs[-1] = SlotRun(last.run_id, record["state"], reason, len(record.get("attempts") or []))
        slot_state.state = record["state"]
        settled = True
    if settled:
        run.save()


def run_pass(run: Pass, progress: Callable[[str], object] = lambda _: None) -> Pass:
    """Run every slot not yet done, in order, saving the state before and after each; a quota stop pauses the
    pass."""
    close_interrupted(run)
    problems = start_problems(run)
    if problems:
        raise PassRefusedError(f"pass {run.pass_id} refused before starting a run:\n" + "\n".join(problems))
    run.state = "running"
    run.save()
    progress(f"pass {run.pass_id}: state file {run.file}")
    for number, slot_state in enumerate(run.slots, start=1):
        if slot_state.done:
            continue
        slot = slot_state.slot
        tasks, book = run.folders.for_task(slot.task_id)
        # A resumed slot's earlier runs, each failed, go into the new run's record as it is written.
        retries = [{"run_id": r.run_id, "failure_reason": r.failure_reason or ""} for r in slot_state.runs]
        # The run is named in the state file before it starts, so a stop at any point leaves it known by its slot.
        run_id = new_run_id(slot.task_id, slot.arm)
        slot_state.runs.append(SlotRun(run_id, RUNNING, None, 0))
        slot_state.state = RUNNING
        run.save()
        record = run_and_grade(
            slot.task_id,
            slot.arm,
            tasks,
            book,
            run.folders.keys,
            run.folders.runs,
            run.config,
            retries,
            run_id=run_id,
            slot={"pass_id": run.pass_id, "repeat": slot.repeat},
        )
        slot_state.runs[-1] = SlotRun(
            record["run_id"], record["state"], record["failure_reason"], len(record["attempts"])
        )
        slot_state.state = record["state"]
        progress(f"{number}/{len(run.slots)} {slot}: {record['run_id']} {record['state']}")
        if record["failure_reason"] == QUOTA_REASON:
            run.state = "paused"
            run.save()
            return run
        run.save()
    run.state = "complete"
    run.save()
    return run


def ungraded_runs(run: Pass) -> list[tuple[SlotState, SlotRun]]:
    """The completed runs a resume kept ungraded (their task, key or grader changed since they ran): outcomes the
    pass has, and cannot count, until the owner settles them."""
    return [(s, r) for s in run.slots for r in s.runs if r.state == "completed" and r.failure_reason]


def status_lines(run: Pass) -> list[str]:
    """The pass's state, its slots by state, and every failed run with its reason."""
    counts = {state: sum(s.state == state for s in run.slots) for state in SLOT_STATES}
    shown = ", ".join(f"{n} {state}" for state, n in counts.items() if n)
    lines = [f"pass {run.pass_id}: {run.state}, {len(run.slots)} slots: {shown}", f"state file: {run.file}"]
    failed = run.failed_runs()
    lines.append(f"failed runs: {len(failed)}")
    for slot_state, slot_run in failed:
        now = "" if slot_state.state == "failed" else f" (retried; the slot is now {slot_state.state})"
        lines.append(f"  {slot_state.slot}: {slot_run.run_id}: {slot_run.failure_reason}{now}")
    ungraded = ungraded_runs(run)
    if ungraded:
        lines.append(f"completed runs not graded: {len(ungraded)}")
        lines += [f"  {s.slot}: {r.run_id}: {r.failure_reason}" for s, r in ungraded]
    return lines
