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
    "output",
    "grade",
)
# "answer" is the answer key's hash; the plan refuses a grade when it changed after the run.
HASH_FIELDS = ("dataset", "task", "skill", "checklist", "grader", "answer", "config")
STATES = ("completed", "failed", "graded", "mapped", "published")


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
    return record
