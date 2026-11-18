"""One run: one task under one arm in a fresh workspace, with retries, recorded in full."""

import hashlib
import json
import os
import secrets
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from casebook.model.files import METADATA, REAL_TICKERS, read_json, read_manifest
from casebook.runner.cli import arguments, cli_version, run_environment, start
from casebook.runner.config import INSTRUCTIONS, LOADING_TOOL, REPO, SharedConfig, tree_sha256
from casebook.runner.freeze import freeze_identity, require_freeze
from casebook.runner.preflight import (
    OutsideBookError,
    RunRefusedError,
    require_book_files,
    require_cutoff,
    require_household,
    require_real_tickers,
    require_sealed,
)
from casebook.runner.record import RETRIES, SKILLS_LOADED, SLOT, check_record
from casebook.runner.sandbox import Sandbox, seed
from casebook.runner.transcript import QUOTA_REASON, Transcript, failure_reason, parse_transcript
from casebook.tasks.fixtures import FixtureError, load_task_fixtures
from casebook.tasks.task import Task

PRIVATE_VARIABLE = "CASEBOOK_PRIVATE"
# Each arm's instruction package as `--plugin-dir` loads it: the plugin's name and the skills it holds. A run's
# instruction counts as loaded when the transcript shows any skill of its arm's own package loaded, whichever one the
# model chose for the task (the owner, 18 November 2026; docs/PLAN.md, Choices and why).
ARM_PACKAGES: dict[str, tuple[str, frozenset[str]]] = {
    "checklist": ("indus-checklist", frozenset({"advisor-checklist"})),
    "skill": (
        "indus-advisor",
        frozenset({"reconciliation-as-of", "tax-lot-rmd", "meeting-follow-up", "compliance-review"}),
    ),
}


class PrivateFolderError(RunRefusedError):
    pass


def private_root() -> Path:
    """Unmapped run records carry real tickers, so they live outside the public repo."""
    value = os.environ.get(PRIVATE_VARIABLE)
    if not value:
        raise PrivateFolderError(f"set {PRIVATE_VARIABLE} to the private folder outside this repo")
    path = Path(value).resolve()
    if path == REPO or REPO in path.parents:
        raise PrivateFolderError(f"{PRIVATE_VARIABLE} is inside the public repo ({path})")
    path.mkdir(parents=True, exist_ok=True)
    return path


def sealed_files(book: Path, keys: Path | None) -> list[Path]:
    folders = [book / "sealed"] + ([keys] if keys else [])
    return sorted(p for folder in folders if folder.exists() for p in folder.rglob("*") if p.is_file())


class ToolsMismatchError(RunRefusedError):
    pass


def require_tools(task: Task, config: SharedConfig) -> None:
    if set(task.allowed_tools) | {LOADING_TOOL} != set(config.tools) | set(config.crm_tools):
        raise ToolsMismatchError(
            f"task {task.task_id} allows {task.allowed_tools}; the shared config has {config.tools}"
            + (f" and the CRM sandbox's {config.crm_tools}" if config.crm_tools else "")
        )


def prepare(task: Task, book: Path, workspace: Path, keys: Path | None) -> None:
    require_real_tickers(book)
    require_household(book, task.household_id)
    require_book_files(book, task.household_id)
    require_freeze(task, book)
    try:
        load_task_fixtures(book, task.household_id, task.fixtures, task.cutoff, workspace)
    except FixtureError as error:
        raise OutsideBookError(str(error)) from error
    require_sealed(workspace, sealed_files(book, keys))
    require_cutoff(workspace, task.cutoff)


def skills_loaded(arm: str, transcript: Transcript) -> list[str]:
    """The skills of the arm's own package the transcript shows loaded, in order; none for the basic arm. A skill of
    another plugin, or the user's own, never counts, even under the same short name."""
    if arm not in ARM_PACKAGES:
        return []
    package, held = ARM_PACKAGES[arm]
    loaded: list[str] = []
    for name in transcript.skills_invoked:
        prefix, _, short = name.rpartition(":")
        if prefix == package and short in held:
            loaded.append(name)
    return loaded


def instruction_loaded(arm: str, transcript: Transcript) -> bool:
    return arm == "basic" or bool(skills_loaded(arm, transcript))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class RunInputs:
    task: Task
    arm: str
    book: Path
    keys: Path | None
    grader_sha256: str
    key_sha256: str
    # The slot's earlier runs, each failed, when a pass resumes it (docs/PLAN.md: "a new attempt recorded under
    # "retries" in the run record"): each as {"run_id", "failure_reason"}.
    retries: tuple[dict[str, str], ...] = ()
    # Given by a pass before the run starts, so the pass can record the run as running first: the run's ID, and the
    # slot it runs for, {"pass_id", "repeat"}, which its record keeps (reviewers A and B, slice 13 round 1).
    run_id: str | None = None
    slot: dict[str, str | int] | None = None


def new_run_id(task_id: str, arm: str) -> str:
    return f"{task_id}-{arm}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(2)}"


def run_task(inputs: RunInputs, config: SharedConfig, private: Path) -> dict[str, Any]:
    task, arm = inputs.task, inputs.arm
    config = config.for_tools(task.allowed_tools)
    require_tools(task, config)
    run_id = inputs.run_id or new_run_id(task.task_id, arm)
    folder = private / "runs" / run_id
    folder.mkdir(parents=True)
    attempts: list[dict[str, Any]] = []
    errors: list[str] = []
    transcript: Transcript | None = None
    reason: str | None = None
    loaded = False
    started = _now()
    hashes: dict[str, str | None] = {}
    frozen_under: str | None = None
    version = cli_version()
    args: list[str] = []
    crm: Sandbox | None = None
    for attempt in range(1, config.retries + 2):
        workspace = Path(tempfile.mkdtemp(prefix="casebook-workspace-"))
        try:
            prepare(task, inputs.book, workspace, inputs.keys)
            # What the attempt runs under is taken as it starts, not read back after the CLI ends; the record keeps
            # the last attempt's, whose output it is. A skill, the checklist, the book or the freeze changed while
            # an attempt ran, or between attempts, never relabels output (reviewers A and B, slice 12).
            hashes = _inputs_hashes(inputs, config)
            frozen_under = freeze_identity()
            # A fresh sandbox per attempt, in the run folder, never the workspace.
            crm = seed(inputs.book, task.cutoff, folder / f"crm-{attempt}") if config.crm_tools else None
            args = arguments(task.prompt, arm, config, crm.mcp_config if crm else None)
            attempt_started = _now()
            completed = start(args, workspace, config)
            transcript = parse_transcript(completed.stdout)
            reason = failure_reason(completed.exit_code, completed.timed_out, transcript, completed.stderr)
            if completed.launch_error:
                reason = f"the CLI could not start: {completed.launch_error}"
            loaded = instruction_loaded(arm, transcript)
            if reason is None and not loaded:
                reason = "the transcript shows no instruction loaded"
            (folder / f"attempt-{attempt}.jsonl").write_text(completed.stdout, encoding="utf-8")
            (folder / f"attempt-{attempt}.stderr.txt").write_text(completed.stderr, encoding="utf-8")
            shutil.copytree(workspace, folder / f"workspace-{attempt}")
            attempts.append(
                {"attempt": attempt, "started_utc": attempt_started, "ended_utc": _now(), "failure_reason": reason}
            )
            if reason:
                errors.append(f"attempt {attempt}: {reason}")
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
        if reason is None or reason == QUOTA_REASON:
            break
    last = len(attempts)
    record: dict[str, Any] = {
        "run_id": run_id,
        "task_id": task.task_id,
        "arm": arm,
        "state": "failed" if reason else "completed",
        "failure_reason": reason,
        "dataset": {
            "book": inputs.book.as_posix(),
            "version": read_manifest(inputs.book).version,
            "household_id": task.household_id,
            "real_tickers": read_json(inputs.book, METADATA).get("securities") == REAL_TICKERS,
        },
        "hashes": hashes,
        "cli_version": version,
        "model_requested": config.model,
        "models_reported": transcript.reported_models if transcript else [],
        "started_utc": started,
        "ended_utc": _now(),
        "settings": config.as_dict(),
        "tools_and_permissions": {
            "arguments": args,
            "environment_keys": sorted(run_environment()),
            "instruction": None if INSTRUCTIONS[arm] is None else INSTRUCTIONS[arm].name,  # type: ignore[union-attr]
        },
        "instruction_loaded": loaded,
        # Which of the arm's own skills the last attempt loaded, so a result can say which one the model chose.
        SKILLS_LOADED: skills_loaded(arm, transcript) if transcript else [],
        "transcript": {"file": f"attempt-{last}.jsonl", "events": len(transcript.events) if transcript else 0},
        "attempts": attempts,
        "errors": errors,
        "token_use": transcript.token_use if transcript else {},
        "crm_sandbox_diff": crm.diff() if crm else None,
        "freeze": frozen_under,
        **({RETRIES: [dict(r) for r in inputs.retries]} if inputs.retries else {}),
        **({SLOT: dict(inputs.slot)} if inputs.slot else {}),
        "output": transcript.final_text if transcript and not reason else None,
        "grade": None,
    }
    check_record(record)
    (folder / "record.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def _inputs_hashes(inputs: RunInputs, config: SharedConfig) -> dict[str, str | None]:
    return {
        "dataset": _manifest_sha(inputs.book),
        "task": inputs.task.sha256,
        "skill": tree_sha256(INSTRUCTIONS["skill"]),
        "checklist": tree_sha256(INSTRUCTIONS["checklist"]),
        "grader": inputs.grader_sha256,
        "answer": inputs.key_sha256,
        "config": config.sha256(),
    }


def _manifest_sha(book: Path) -> str:
    return hashlib.sha256((book / "manifest.json").read_bytes()).hexdigest()


type Grader = Callable[[str, Path], dict[str, Any]]


class GradeRefusedError(RuntimeError):
    pass


def grade_record(record: dict[str, Any], folder: Path, grade: Grader, hashes: dict[str, str]) -> dict[str, Any]:
    """A failed run is never graded; a changed task, key or grader refuses the grade."""
    if record["state"] != "completed":
        raise GradeRefusedError(f"run {record['run_id']} is {record['state']}; only a completed run is graded")
    for name in ("task", "answer", "grader"):
        if record["hashes"][name] != hashes[name]:
            raise GradeRefusedError(f"run {record['run_id']}: the {name} changed since the run")
    workspace = folder / f"workspace-{len(record['attempts'])}"
    graded = {**record, "state": "graded", "grade": grade(record["output"], workspace)}
    check_record(graded)
    (folder / "record.json").write_text(json.dumps(graded, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return graded
