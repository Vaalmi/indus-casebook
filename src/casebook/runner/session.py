"""`casebook run`: key, run, grade and map one task under one arm; and `casebook canary`."""

import hashlib
import json
from pathlib import Path
from typing import Any

from casebook.graders.follow_up import FollowUp, client_message, tone_context
from casebook.graders.jury import tone
from casebook.graders.registry import GraderSpec, grader
from casebook.model.crm import parse_crm_diff
from casebook.model.files import json_text, read_manifest
from casebook.model.ledger import is_private_task_id
from casebook.publish.mapper import map_to_aliases
from casebook.publish.private_set import private_households
from casebook.runner.config import SharedConfig
from casebook.runner.freeze import require_freeze
from casebook.runner.preflight import RunRefusedError, require_book_files, require_household, require_real_tickers
from casebook.runner.run import Grader, GradeRefusedError, RunInputs, grade_record, private_root, run_task
from casebook.tasks.task import HELD_GRADERS, HELD_WORKFLOWS, Task, find_task

# Where a held workflow's keys go whatever --keys says: out/keys/, which the release script ignores.
HELD_KEYS = Path("out/keys")


class PrivateTaskError(RunRefusedError):
    pass


def is_private(task: Task, tasks: Path) -> bool:
    """Whether the task is one of the private set: loaded from `$CASEBOOK_PRIVATE`, with a private ID. A private
    ID in a public folder, or a public one in the private folder, is refused (docs/SPEC.md, Private set)."""
    inside = tasks.resolve().is_relative_to(private_root())
    if is_private_task_id(task.task_id) != inside:
        where = "$CASEBOOK_PRIVATE" if inside else "the public repo"
        raise PrivateTaskError(
            f"task {task.task_id} was loaded from {where} ({tasks}); private tasks are X-..., "
            "kept and loaded only in $CASEBOOK_PRIVATE/tasks"
        )
    return inside


def refuse_private_pairs(task: Task, book: Path) -> None:
    """A public task never runs on a book that holds a private pair: its key, its CRM sandbox and its published
    record would carry the private households (reviewers A and B, slice 11 round 1)."""
    held = sorted({h.household_id for h in read_manifest(book).households} & private_households())
    if held:
        raise PrivateTaskError(
            f"public task {task.task_id} cannot run on {book}: it holds the private pair households {', '.join(held)}; "
            "public tasks run on the public build (out/real/)"
        )


def keys_root_for(task: Task, keys_root: Path) -> Path:
    """A reconciliation key is published (docs/PLAN.md, Where files go); tax-lot and RMD keys, and a
    reconciliation key that computes an RMD, are held until the tax review, out of `published/`, and
    slice 16's release gate refuses them."""
    return HELD_KEYS if held(task) else keys_root


def held(task: Task) -> bool:
    """Whether the task's key and verdict wait for the tax review: every tax-lot and RMD task, and a
    reconciliation task whose key computes an RMD (docs/SPEC.md: their pages show "sources and outputs
    only, with no verdict and no failure marking, until review")."""
    return task.workflow in HELD_WORKFLOWS or task.grader in HELD_GRADERS


def published_record(task: Task, mapped: dict[str, Any]) -> dict[str, Any]:
    """The record as published: a held task's without its grade, which stays in the private run folder."""
    return {**mapped, "grade": None, "verdict_held": True} if held(task) and mapped["state"] != "failed" else mapped


def write_key(task_id: str, key: Any, keys_root: Path, version: str) -> tuple[Path, str]:
    """The key is sealed answer material: a run's preflight refuses it in a workspace."""
    folder = keys_root / version
    folder.mkdir(parents=True, exist_ok=True)
    text = json_text(key.to_dict())
    (folder / f"{task_id}.json").write_text(text, encoding="utf-8")
    return folder, hashlib.sha256(text.encode()).hexdigest()


def grading(task: Task, spec: GraderSpec, key: Any, record: dict[str, Any]) -> Grader:
    """How a run is graded: on its output and fixtures; a follow-up task's also on its CRM sandbox diff and on
    the tone jury's votes on its client message, every one of which the grade keeps."""
    if not spec.follow_up:
        return lambda output, workspace: spec.grade(output, key, workspace).to_dict()

    def grade(output: str, workspace: Path) -> dict[str, Any]:
        stored = record["crm_sandbox_diff"]
        if stored is None:
            raise GradeRefusedError(f"run {record['run_id']} of follow-up task {task.task_id} has no CRM sandbox diff")
        message = client_message(output)
        votes = tone(message, tone_context(task.justified_conclusion)) if message is not None else None
        follow_up = FollowUp(task.household_id, parse_crm_diff(stored), votes)
        graded: dict[str, Any] = spec.grade(output, key, workspace, follow_up).to_dict()
        return graded | {"tone": votes.to_dict() if votes else None}

    return grade


def run_and_grade(
    task_id: str, arm: str, tasks: Path, book: Path, keys_root: Path, published: Path, config: SharedConfig
) -> dict[str, Any]:
    task = find_task(tasks, task_id)
    secret = is_private(task, tasks)
    if not secret:
        refuse_private_pairs(task, book)
    require_real_tickers(book)
    require_household(book, task.household_id)
    require_book_files(book, task.household_id)
    # Freeze before held-out runs: refused before the key is computed, so no held-out key is written either.
    require_freeze(task, book)
    spec = grader(task.grader)
    key = spec.key(book, task.household_id, task.grader_params)
    private = private_root()
    # A private task's key, like its unmapped record, stays in $CASEBOOK_PRIVATE.
    root = private / "keys" if secret else keys_root_for(task, keys_root)
    keys, key_sha = write_key(task.task_id, key, root, read_manifest(book).version)
    record = run_task(RunInputs(task, arm, book, keys, spec.sha256(), key_sha), config, private)
    folder = private / "runs" / record["run_id"]
    if record["state"] == "completed":
        # Hashed again now, from the files: a task, key or grader that changed since the run refuses the grade.
        key_file = keys / f"{task.task_id}.json"
        hashes = {
            "task": find_task(tasks, task_id).sha256,
            "answer": hashlib.sha256(key_file.read_bytes()).hexdigest(),
            "grader": spec.sha256(),
        }
        record = grade_record(record, folder, grading(task, spec, key, record), hashes)
    if secret:
        # Nothing of a private run is published: its unmapped record stays in the private run folder.
        return record
    mapped = map_to_aliases(record)
    if mapped["state"] == "graded":
        mapped["state"] = "mapped"
    out = published / task.task_id
    out.mkdir(parents=True, exist_ok=True)
    public = published_record(task, mapped)
    (out / f"{record['run_id']}.json").write_text(json.dumps(public, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    transcript = folder / record["transcript"]["file"]
    if transcript.is_file():
        lines = [
            json.dumps(map_to_aliases(json.loads(line))) for line in transcript.read_text().splitlines() if line.strip()
        ]
        (out / f"{record['run_id']}.transcript.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return public
