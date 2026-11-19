"""The run record: every field the spec lists, so a run can be judged and repeated."""

from typing import Any

# docs/SPEC.md, Runs and results: dataset, task, skill, checklist and grader hashes; CLI
# version; requested and reported model IDs; UTC times; settings; tools and permissions;
# transcript; retries and errors; token use; CRM sandbox diff.
RECORD_FIELDS = (
    "run_id",
    "task_id",
    "arm",
    "state",
    "failure_reason",
    "dataset",
    "hashes",
    "cli_version",
    "model_requested",
    "models_reported",
    "started_utc",
    "ended_utc",
    "settings",
    "tools_and_permissions",
    "instruction_loaded",
    "transcript",
    "attempts",
    "errors",
    "token_use",
    "crm_sandbox_diff",
    # The freeze the run ran under (its record's sha256), or None before any freeze.
    "freeze",
    "output",
    "grade",
)
# "answer" is the answer key's hash; the plan refuses a grade when it changed after the run.
HASH_FIELDS = ("dataset", "task", "skill", "checklist", "grader", "answer", "config")
STATES = ("completed", "failed", "graded", "mapped", "published")
# A run a pass started again after a failed run of the same slot names each earlier run and why it failed
# (docs/PLAN.md: "a new attempt recorded under "retries" in the run record"); a first run has no such field.
RETRIES = "retries"
RETRY_FIELDS = ("run_id", "failure_reason")
# A pass's run names the slot it ran for, given before it starts, so a run the pass never recorded (the process
# stopped between the run and the pass's state file) is still known by its slot (reviewers A and B, slice 13
# round 1); a run outside a pass has no such field.
SLOT = "slot"
# The skills of the arm's own package a run loaded (the owner, 18 November 2026); records written before that lack it.
SKILLS_LOADED = "skills_loaded"
SLOT_FIELDS = ("pass_id", "repeat")
# A run graded again after it ran, with no new run (`casebook regrade`; the owner, 18 November 2026): when, under
# which freeze and decision, and the grader and grade it had before. A run never regraded has no such field.
REGRADED = "regraded"
REGRADED_FIELDS = ("utc", "freeze", "decision", "grader_before", "grade_before")


class RunRecordError(ValueError):
    pass


def check_record(record: dict[str, Any]) -> dict[str, Any]:
    missing = [f for f in RECORD_FIELDS if f not in record]
    if missing:
        raise RunRecordError(f"run record {record.get('run_id', '?')} lacks {', '.join(missing)}")
    missing_hashes = [h for h in HASH_FIELDS if h not in (record["hashes"] or {})]
    if missing_hashes:
        raise RunRecordError(f"run record {record['run_id']} lacks the {', '.join(missing_hashes)} hash")
    if record["state"] not in STATES:
        raise RunRecordError(f"run record {record['run_id']}: state {record['state']!r} is not one of {STATES}")
    if record["state"] == "failed" and (not record["failure_reason"] or record["grade"] is not None):
        raise RunRecordError(f"run record {record['run_id']}: a failed run has a reason and no grade")
    retries = record.get(RETRIES, [])
    if not isinstance(retries, list) or any(
        not isinstance(r, dict) or sorted(r) != sorted(RETRY_FIELDS) or not r["failure_reason"] for r in retries
    ):
        raise RunRecordError(f"run record {record['run_id']}: each retry names an earlier run and why it failed")
    loaded = record.get(SKILLS_LOADED, [])
    if not isinstance(loaded, list) or not all(isinstance(s, str) for s in loaded):  # pyright: ignore[reportUnknownVariableType]
        raise RunRecordError(f"run record {record['run_id']}: its skills loaded are a list of skill names")
    regraded = record.get(REGRADED)
    if regraded is not None and (not isinstance(regraded, dict) or sorted(regraded) != sorted(REGRADED_FIELDS)):  # pyright: ignore[reportUnknownArgumentType]
        raise RunRecordError(f"run record {record['run_id']}: a regrade names {', '.join(REGRADED_FIELDS)}")
    if regraded is not None and record["state"] == "failed":
        raise RunRecordError(f"run record {record['run_id']}: a failed run is never graded, so never regraded")
    if SLOT in record and not is_slot(record[SLOT]):
        raise RunRecordError(f"run record {record['run_id']}: its slot names a pass and a repeat from 1")
    return record


def is_slot(value: Any) -> bool:
    """`{"pass_id": <a non-blank string>, "repeat": <a whole number from 1>}`."""
    return (
        isinstance(value, dict)
        and sorted(value) == sorted(SLOT_FIELDS)  # pyright: ignore[reportUnknownArgumentType]
        and isinstance(value["pass_id"], str)
        and bool(value["pass_id"].strip())
        and type(value["repeat"]) is int
        and value["repeat"] >= 1
    )
