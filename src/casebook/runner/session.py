"""`casebook run`: key, run, grade and map one task under one arm; and `casebook canary`."""

import hashlib
import json
from pathlib import Path
from typing import Any

from casebook.graders.registry import grader
from casebook.model.files import household_dir, json_text, read_manifest
from casebook.publish.mapper import map_to_aliases
from casebook.runner.config import SharedConfig
from casebook.runner.preflight import require_book_files, require_household, require_real_tickers
from casebook.runner.run import RunInputs, grade_record, private_root, run_task
from casebook.tasks.task import find_task


def write_key(task_id: str, key: Any, keys_root: Path, version: str) -> tuple[Path, str]:
    """The key is sealed answer material: a run's preflight refuses it in a workspace.

    A reconciliation key is published (docs/PLAN.md, Where files go); tax-lot and RMD keys are
    held until review, and slice 16's release gate refuses them.
    """
    folder = keys_root / version
    folder.mkdir(parents=True, exist_ok=True)
    text = json_text(key.to_dict())
    (folder / f"{task_id}.json").write_text(text, encoding="utf-8")
    return folder, hashlib.sha256(text.encode()).hexdigest()


def run_and_grade(
    task_id: str, arm: str, tasks: Path, book: Path, keys_root: Path, published: Path, config: SharedConfig
) -> dict[str, Any]:
    task = find_task(tasks, task_id)
    require_real_tickers(book)
    require_household(book, task.household_id)
    require_book_files(book, task.household_id)
    spec = grader(task.grader)
    key = spec.key(book / household_dir(task.household_id), task.grader_params)
    keys, key_sha = write_key(task.task_id, key, keys_root, read_manifest(book).version)
    private = private_root()
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
        record = grade_record(
            record, folder, lambda output, workspace: spec.grade(output, key, workspace).to_dict(), hashes
        )
    mapped = map_to_aliases(record)
    if mapped["state"] == "graded":
        mapped["state"] = "mapped"
    out = published / task.task_id
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{record['run_id']}.json").write_text(json.dumps(mapped, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    transcript = folder / record["transcript"]["file"]
    if transcript.is_file():
        lines = [
            json.dumps(map_to_aliases(json.loads(line))) for line in transcript.read_text().splitlines() if line.strip()
        ]
        (out / f"{record['run_id']}.transcript.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return mapped
