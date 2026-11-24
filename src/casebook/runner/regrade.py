"""`casebook regrade <pass id>`: grade a pass's public answers again under today's graders, with no new run.

The owner's decision of 18 November 2026 (option 1 of `docs/decisions/2026-11-18-fabricated-figure-false-zeros.md`)
changed the fabricated-figure rule after the full pass had run, and had its stored answers graded again: no model
runs again, and a follow-up run keeps the jury's votes it was graded with (the jury is never called here). Under its
option 1a the private set was run again under the new freeze (`casebook pass --private`), so a full pass's private
slots are never regraded. The owner's decision of 19 November 2026 (`docs/decisions/2026-11-19-billing-group-totals.md`)
widened the rule again and had both passes graded again, the private-only pass too: its records, and the private
outcome counts, say that its grader changed after it ran.

A regrade is refused unless the freeze matches today's hashes, so every regraded run names the freeze it was graded
under; unless the task and the key are the ones the run ran with (the key is computed again and must hash as the
record's answer key); and, for a follow-up run, unless its stored votes read back as stored and are on the message
its answer drafted. Each run's record keeps the grade it had and the grader that gave it, under `regraded`. A failed
run of the pass is never graded; under the same checks it stands under the regrade's freeze with the rest of its pass
(found building the results page: the pass was split in two, its failed runs shown as not run).
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from casebook.graders.follow_up import FollowUp, client_message, tone_context
from casebook.graders.jury import ToneResult, prompt_for
from casebook.graders.registry import GraderSpec, grader
from casebook.model.crm import parse_crm_diff
from casebook.model.files import json_text, read_manifest
from casebook.model.ledger import is_private_task_id
from casebook.review_statement import statement_of
from casebook.runner.config import INSTRUCTIONS, SharedConfig, tree_sha256
from casebook.runner.freeze import drift, freeze_identity
from casebook.runner.full_pass import Pass
from casebook.runner.preflight import RunRefusedError
from casebook.runner.record import REGRADED, check_record
from casebook.runner.run import private_root
from casebook.runner.session import finish_run, keys_root_for, write_key
from casebook.tasks.task import Task, find_task

DECISION = "docs/decisions/2026-11-19-billing-group-totals.md"
# The states of a run whose answer was graded: only these are graded again. A failed run is never graded; it
# stands under the regrade's freeze with the rest of its pass.
GRADED = ("graded", "mapped", "published")
FAILED = "failed"


class RegradeRefusedError(RunRefusedError):
    pass


@dataclass(frozen=True)
class Regraded:
    """One run graded again: its slot, and its score and critical fail before and after."""

    slot: str
    run_id: str
    before: tuple[int, str | None] | None  # None for a failed run, never graded
    after: tuple[int, str | None] | None

    def __str__(self) -> str:
        if self.before is None or self.after is None:
            return f"{self.slot}: {self.run_id}: failed run, never graded; stands under this freeze"

        def shown(grade: tuple[int, str | None]) -> str:
            return f"{grade[0]}" + (f" ({grade[1]})" if grade[1] else "")

        return f"{self.slot}: {self.run_id}: {shown(self.before)} -> {shown(self.after)}"


def stored_tone(task: Task, output: str, grade: dict[str, Any]) -> ToneResult | None:
    """The jury's votes a follow-up run was graded with, refused unless they are on the message its answer drafts
    now: the votes are reused, never asked for again."""
    message = client_message(output)
    stored = grade.get("tone")
    if message is None:
        if stored is not None:
            raise RegradeRefusedError(f"task {task.task_id}: votes are stored for an answer that drafts no message")
        return None
    if stored is None:
        raise RegradeRefusedError(f"task {task.task_id}: the answer drafts a message and no votes are stored")
    try:
        votes = ToneResult.from_dict(stored)
    except (KeyError, TypeError, ValueError) as error:
        raise RegradeRefusedError(f"task {task.task_id}: the stored votes cannot be read back: {error}") from error
    if votes.prompt != prompt_for(message, tone_context(task.justified_conclusion)):
        raise RegradeRefusedError(f"task {task.task_id}: the stored votes are not on the message the answer drafts")
    return votes


def regrade_record(task: Task, spec: GraderSpec, key: Any, record: dict[str, Any], workspace: Path) -> dict[str, Any]:
    """The run's grade under today's grader: a follow-up run's on its stored CRM diff and its stored votes."""
    output = str(record["output"])
    if not spec.follow_up:
        graded: dict[str, Any] = spec.grade(output, key, workspace).to_dict()
        return graded
    diff = record["crm_sandbox_diff"]
    if diff is None:
        raise RegradeRefusedError(f"run {record['run_id']} of follow-up task {task.task_id} has no CRM sandbox diff")
    votes = stored_tone(task, output, record["grade"])
    follow_up = FollowUp(task.household_id, parse_crm_diff(diff), votes)
    graded = spec.grade(output, key, workspace, follow_up).to_dict()
    return graded | {"tone": votes.to_dict() if votes else None}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def regrade_run(
    task: Task, tasks: Path, book: Path, keys_root: Path, published: Path, run_id: str, secret: bool = False
) -> Regraded:
    """Grade one run again, its earlier grade kept under `regraded`, and publish a public one again; a private one
    (`secret`) stays in `$CASEBOOK_PRIVATE`, its key there too."""
    folder = private_root() / "runs" / run_id
    record: dict[str, Any] = json.loads((folder / "record.json").read_text(encoding="utf-8"))
    failed = record["state"] == FAILED
    if not failed and (record["state"] not in GRADED or not record["grade"]):
        raise RegradeRefusedError(f"run {run_id} is {record['state']}; only a graded or failed run is regraded")
    spec = grader(task.grader)
    key = spec.key(book, task.household_id, task.grader_params)
    if hashlib.sha256(json_text(key.to_dict()).encode()).hexdigest() != record["hashes"]["answer"]:
        raise RegradeRefusedError(f"run {run_id}: the answer key computed now is not the one it ran with")
    if task.sha256 != record["hashes"]["task"]:
        raise RegradeRefusedError(f"run {run_id}: the task changed since the run")
    # Graded again under today's freeze, the run stands under it: only if what it ran is what that freeze holds.
    now = {
        "skill": tree_sha256(INSTRUCTIONS["skill"]),
        "checklist": tree_sha256(INSTRUCTIONS["checklist"]),
        "config": SharedConfig().for_tools(task.allowed_tools).sha256(),
    }
    changed = [name for name, digest in now.items() if record["hashes"][name] != digest]
    if changed:
        raise RegradeRefusedError(f"run {run_id}: its {', '.join(changed)} changed since the run; run it again")
    previous = record.get(REGRADED)
    before = previous["grade_before"] if previous else record["grade"]
    grader_before = previous["grader_before"] if previous else record["hashes"]["grader"]
    grade = None if failed else regrade_record(task, spec, key, record, folder / f"workspace-{len(record['attempts'])}")
    record = {
        **record,
        "state": FAILED if failed else "graded",
        "grade": grade,
        "hashes": {**record["hashes"], "grader": spec.sha256()},
        REGRADED: {
            "utc": _now(),
            "freeze": freeze_identity(),
            "decision": DECISION,
            "grader_before": grader_before,
            "grade_before": before,
        },
    }
    check_record(record)
    (folder / "record.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    statement = statement_of(book)
    root = private_root() / "keys" if secret else keys_root_for(task, keys_root, statement)
    # Written again where the key now belongs: a tax task a review statement released moves its key from out/keys/ to
    # the published keys, where the release takes it (slice 17).
    keys, _ = write_key(task.task_id, key, root, read_manifest(book).version)
    finish_run(task, tasks, secret, spec, key, keys, record, published, statement)
    if before is None or grade is None:
        return Regraded(f"{task.task_id} {record['arm']}", run_id, None, None)
    score = (int(before["score"]), before["critical_fail"]), (int(grade["score"]), grade["critical_fail"])
    return Regraded(f"{task.task_id} {record['arm']}", run_id, *score)


def is_private_pass(run: Pass) -> bool:
    """A pass of the private set alone (`casebook pass --private`)."""
    return bool(run.slots) and all(is_private_task_id(s.slot.task_id) for s in run.slots)


def regrade_pass(
    run: Pass, progress: Callable[[str], object] = lambda _: None, book: Path | None = None
) -> list[Regraded]:
    """Every public slot's standing run graded again, in the pass's order, or, for a private-only pass, every
    private slot's; refused before any is unless the freeze matches today's hashes. A full pass's private slots
    are not: a private-only pass ran them again (option 1a). `book`: the public runs' book in place of the one the
    pass ran on: a book rebuilt under a review statement, under its new version, whose statement decides what is
    published and whose version names the keys' folder (reviewers A and B, slice 17 round 1, D1). Each run is still
    graded only against the very key it ran with."""
    problems = drift()
    if problems:
        shown = "\n".join(p.removeprefix(": ").strip() for p in problems)
        raise RegradeRefusedError(f"a regrade runs only under the recorded freeze:\n{shown}")
    secret = is_private_pass(run)
    done: list[Regraded] = []
    for slot_state in run.slots:
        task_id = slot_state.slot.task_id
        last = slot_state.runs[-1] if slot_state.runs else None
        if is_private_task_id(task_id) != secret or last is None or last.state not in (*GRADED, FAILED):
            continue
        tasks, ran_on = run.folders.for_task(task_id)
        task = find_task(tasks, task_id)
        on = book if book is not None and not is_private_task_id(task_id) else ran_on
        result = regrade_run(task, tasks, on, run.folders.keys, run.folders.runs, last.run_id, secret)
        done.append(result)
        progress(str(result))
    return done
