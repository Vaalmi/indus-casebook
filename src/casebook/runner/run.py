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
from casebook.runner.preflight import (
    OutsideBookError,
    RunRefusedError,
    require_book_files,
    require_cutoff,
    require_household,
    require_real_tickers,
    require_sealed,
)
from casebook.runner.record import check_record
from casebook.runner.transcript import Transcript, failure_reason, parse_transcript
from casebook.tasks.fixtures import FixtureError, load_task_fixtures
from casebook.tasks.task import Task

PRIVATE_VARIABLE = "CASEBOOK_PRIVATE"
# The instruction each arm must show as loaded, by workflow (docs/PLAN.md, Choices and why).
ARM_SKILLS: dict[str, dict[str, str]] = {
    "checklist": {"reconciliation": "advisor-checklist", "tax_lot_rmd": "advisor-checklist"},
    "skill": {"reconciliation": "reconciliation-as-of", "tax_lot_rmd": "tax-lot-rmd"},
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
    if set(task.allowed_tools) | {LOADING_TOOL} != set(config.tools):
        raise ToolsMismatchError(
            f"task {task.task_id} allows {task.allowed_tools}; the shared config has {config.tools}"
        )


def prepare(task: Task, book: Path, workspace: Path, keys: Path | None) -> None:
    require_real_tickers(book)
    require_household(book, task.household_id)
    require_book_files(book, task.household_id)
    try:
        load_task_fixtures(book, task.household_id, task.fixtures, task.cutoff, workspace)
    except FixtureError as error:
        raise OutsideBookError(str(error)) from error
    require_sealed(workspace, sealed_files(book, keys))
    require_cutoff(workspace, task.cutoff)


def instruction_loaded(arm: str, workflow: str, transcript: Transcript) -> bool:
    if arm == "basic":
        return True
    wanted = ARM_SKILLS[arm].get(workflow)
    return wanted is not None and any(s.split(":")[-1] == wanted for s in transcript.skills_invoked)


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


def run_task(inputs: RunInputs, config: SharedConfig, private: Path) -> dict[str, Any]:
    task, arm = inputs.task, inputs.arm
    require_tools(task, config)
    run_id = f"{task.task_id}-{arm}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(2)}"
    folder = private / "runs" / run_id
    folder.mkdir(parents=True)
    attempts: list[dict[str, Any]] = []
    errors: list[str] = []
    transcript: Transcript | None = None
    reason: str | None = None
    loaded = False
    started = _now()
    version = cli_version()
    args: list[str] = []
    for attempt in range(1, config.retries + 2):
        workspace = Path(tempfile.mkdtemp(prefix="casebook-workspace-"))
        try:
            prepare(task, inputs.book, workspace, inputs.keys)
            args = arguments(task.prompt, arm, config)
            attempt_started = _now()
            completed = start(args, workspace, config)
            transcript = parse_transcript(completed.stdout)
            reason = failure_reason(completed.exit_code, completed.timed_out, transcript, completed.stderr)
            if completed.launch_error:
                reason = f"the CLI could not start: {completed.launch_error}"
            loaded = instruction_loaded(arm, task.workflow, transcript)
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
        if reason is None or reason == "quota":
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
        "hashes": {
            "dataset": _manifest_sha(inputs.book),
            "task": task.sha256,
            "skill": tree_sha256(INSTRUCTIONS["skill"]),
            "checklist": tree_sha256(INSTRUCTIONS["checklist"]),
            "grader": inputs.grader_sha256,
            "answer": inputs.key_sha256,
            "config": config.sha256(),
        },
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
        "transcript": {"file": f"attempt-{last}.jsonl", "events": len(transcript.events) if transcript else 0},
        "attempts": attempts,
        "errors": errors,
        "token_use": transcript.token_use if transcript else {},
        "crm_sandbox_diff": None,
        "output": transcript.final_text if transcript and not reason else None,
        "grade": None,
    }
    check_record(record)
    (folder / "record.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


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
