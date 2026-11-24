"""The results page: every run of the public tasks by task, arm and repeat, with the pairs the spec's change rule
reads, the counts per workflow, the consistency across repeats, and the private set's outcome counts beside the
public ones; never a combined score, and never runs of two tools, versions, models or freezes pooled.

A pass's run names its repeat in its record's `slot`, and is shown in that repeat's column, so the pairs compare
the same repeat even when the runs of one repeat fall under two names; a run outside a pass, with no `slot`, takes
its place by when its slot started.

The private set publishes outcome counts only (docs/SPEC.md, Private set): `private_outcomes` counts the private
runs in `$CASEBOOK_PRIVATE/runs/` per workflow and arm, and `write_private_outcomes` writes those counts, and
nothing else of the private set, to `published/results/private-outcomes.json`. A held workflow's counts are held
only, in the summary and on the page.
"""

import json
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from casebook.model.files import json_text
from casebook.model.ledger import PRIVATE_TASK_ID, is_private_task_id
from casebook.notice import NOTICE
from casebook.publish.private_set import private_set_problems
from casebook.review_statement import ReviewStatement, is_held, is_reviewed
from casebook.runner.record import REGRADED, SLOT
from casebook.site.tasks import ARM_NAMES, ARM_ORDER, cli_name, graded_under, require_named
from casebook.tasks.matrix import BOOK, load_matrix
from casebook.tasks.task import HELD_WORKFLOWS, WORKFLOWS, Task, find_task, load_task

# A slot's outcome: passed or failed by its grader, a failed run (never scored), or held until the tax review.
OUTCOMES = ("passed", "failed", "failed_run", "held")
OUTCOME_NAMES = {"passed": "passed", "failed": "failed", "failed_run": "failed run", "held": "held"}
# The pairs the change rule reads (docs/SPEC.md: "the skill does not beat the generic checklist on paired task
# outcomes"): the skill against each other arm, on the same task and repeat.
COMPARED = (("skill", "checklist"), ("skill", "basic"))
WORKFLOW_NAMES = {
    "reconciliation": "Reconciliation and as-of",
    "meeting": "Meeting prep and follow-up",
    "tax_lot_rmd": "Tax-lot and RMD review",
    "compliance": "Compliance review",
}
ROLE_NAMES = {"trap": "trap task", "twin": "twin task", BOOK: "book-level task"}
# Where the private set's counts are published, under `published/`.
RESULTS_DIR = "results"
PRIVATE_OUTCOMES = "private-outcomes.json"
RECORD = "record.json"
MATRIX = "matrix.toml"
# The outcomes a held workflow may count: no verdict and no failure marking until the tax review (docs/SPEC.md).
HELD_OUTCOMES = ("held",)
_HOUSEHOLD = re.compile(r"(?<![A-Za-z0-9])HH-\d{4}(?!\d)")


class ResultsError(ValueError):
    """Results the page cannot show as they are."""


class PrivateOutcomesError(ResultsError):
    """A private summary that holds more than the private set's outcome counts."""


@dataclass(frozen=True)
class RunName:
    """What a result is named by. Runs under two names are never counted together."""

    tool: str
    version: str
    models: tuple[str, ...]
    effort: str
    # The freeze the run's grade stands under: the one it ran under, or, for a run graded again after it ran
    # (`casebook regrade`, refused unless its skill, checklist and config are that freeze's), the one it was
    # graded again under (the owner, 18 November 2026). Its section names the earlier freeze too.
    freeze: str | None

    @property
    def label(self) -> str:
        effort = f" at {self.effort} effort" if self.effort else ""
        return f"{self.tool} {self.version} · model {', '.join(self.models)}{effort}"

    @property
    def freeze_label(self) -> str:
        return f"freeze {self.freeze[:12]}" if self.freeze else "before the freeze"

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "version": self.version,
            "models": list(self.models),
            "effort": self.effort,
            "freeze": self.freeze,
        }


def run_name(record: dict[str, Any]) -> RunName:
    """A run's name from its record. A failed run whose CLI reported no model is named by the model requested:
    it ran under the same configuration as the runs beside it."""
    tool, version = cli_name(str(record.get("cli_version") or ""))
    models = tuple(str(m) for m in record.get("models_reported") or []) or (str(record.get("model_requested")),)
    return RunName(
        tool=tool or "unnamed tool",
        version=version or "unknown version",
        models=models,
        effort=str((record.get("settings") or {}).get("effort") or ""),
        freeze=graded_under(record),
    )


def ran_under(record: dict[str, Any]) -> str | None:
    """The freeze a regraded run ran under, before it was graded again; None for a run graded as it ran."""
    regraded = record.get(REGRADED)
    return record.get("freeze") if regraded and record.get("freeze") != regraded.get("freeze") else None


@dataclass(frozen=True)
class Outcome:
    kind: str
    run_id: str
    score: int | None = None
    reason: str | None = None

    @property
    def text(self) -> str:
        if self.kind in ("passed", "failed"):
            return f"{self.kind}, {self.score}"
        if self.kind == "failed_run":
            return f"failed run: {self.reason}"
        return "held"


def outcome(record: dict[str, Any], held: bool) -> Outcome:
    """A held task's every run is held, with no verdict and no failure marking, as its task page shows it."""
    run_id = str(record["run_id"])
    if held:
        return Outcome("held", run_id)
    if record["state"] == "failed":
        return Outcome("failed_run", run_id, reason=str(record["failure_reason"]))
    grade = record.get("grade")
    if not grade:
        # A tax task a review statement has since released was published held, with no grade: `casebook regrade`
        # publishes it again with its grade, which the private run folder kept.
        raise ResultsError(
            f"run {run_id} is {record['state']} with no grade, on a task whose verdict is not held "
            "(a task a review statement released is published again with its grade by `casebook regrade`)"
        )
    return Outcome("passed" if grade["passed"] else "failed", run_id, score=int(grade["score"]))


def _retried(record: dict[str, Any]) -> list[str]:
    """The earlier, failed runs of the slot this run was started again for (`casebook pass --resume`: each named
    with its failure reason under the record's `retries`)."""
    return [str(r["run_id"]) for r in record.get("retries") or []]


def standing(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """One task's runs under one arm that stand for their slots, a slot's run being its latest attempt: each run
    but those a later run was retried for, in the order the slots first started, so the nth is the nth repeat."""
    by_id = {str(r["run_id"]): r for r in records}
    superseded = {i for r in records for i in _retried(r)}

    def first(record: dict[str, Any]) -> str:
        earlier = [first(by_id[i]) for i in _retried(record) if i in by_id]
        return min([str(record["started_utc"]), *earlier])

    return sorted((r for r in records if str(r["run_id"]) not in superseded), key=lambda r: (first(r), r["run_id"]))


# Where a run sits among its arm's runs on a task: its pass and repeat (`slot`), or, for a run outside a pass, ""
# and its place among those runs by when its slot started.
type Column = tuple[str, int]


def _columns(records: Sequence[dict[str, Any]]) -> dict[Column, dict[str, Any]]:
    """One task's runs under one arm and one name that stand (`standing`, in order), by column."""
    placed: dict[Column, dict[str, Any]] = {}
    outside = 0
    for record in records:
        slot = record.get(SLOT)
        if slot:
            column = (str(slot["pass_id"]), int(slot["repeat"]))
        else:
            outside += 1
            column = ("", outside)
        if column in placed:
            raise ResultsError(f"runs {placed[column]['run_id']} and {record['run_id']} both stand for one slot")
        placed[column] = record
    return placed


def _column_labels(columns: Sequence[Column]) -> tuple[str, ...]:
    """Each column's heading, "Repeat n", naming the pass too when the runs under one name came from more than
    one."""
    if len({source for source, _ in columns}) <= 1:
        return tuple(f"Repeat {n}" for _, n in columns)
    return tuple(f"Repeat {n}, {source or 'outside a pass'}" for source, n in columns)


def held_count_problems(
    where: str, counts: dict[str, dict[str, dict[str, int]]], released: frozenset[str] = frozenset()
) -> list[str]:
    """A held workflow counted as anything but held: a verdict or a failure before the tax review. `released`: the
    workflows a review statement released a task of, whose counts may hold that task's verdicts; each run of a task
    still held is counted held all the same (`outcome`)."""
    return [
        f"{where}: {workflow} {arm} counts {counts[workflow][arm][kind]} {OUTCOME_NAMES[kind]}, but it is held"
        for workflow in HELD_WORKFLOWS
        if workflow not in released
        for arm in ARM_ORDER
        for kind in OUTCOMES
        if kind not in HELD_OUTCOMES and counts[workflow][arm][kind]
    ]


def _counts(outcomes: Iterable[Outcome]) -> dict[str, int]:
    found = Counter(o.kind for o in outcomes)
    return {kind: found[kind] for kind in OUTCOMES}


def _empty_counts() -> dict[str, dict[str, dict[str, int]]]:
    return {w: {a: dict.fromkeys(OUTCOMES, 0) for a in ARM_ORDER} for w in WORKFLOWS}


@dataclass(frozen=True)
class ArmResult:
    arm: str
    name: str
    outcomes: tuple[Outcome | None, ...]  # by column; None where the repeat has no run under this name

    @property
    def agreement(self) -> str:
        """How many of the repeats agree, on passed, failed, failed run or held."""
        ran = [o.kind for o in self.outcomes if o is not None]
        if not ran:
            return "not run"
        kind, agree = Counter(ran).most_common(1)[0]
        if len(ran) == 1:
            return f"1 run: {OUTCOME_NAMES[kind]}"
        if agree == 1:
            return f"no two of {len(ran)} agree"
        return f"{agree} of {len(ran)} agree: {OUTCOME_NAMES[kind]}"


def compare(one: Outcome | None, other: Outcome | None) -> str:
    """One arm against another on the same task and repeat, by passed or failed."""
    if one is None or other is None:
        return "not run"
    if "held" in (one.kind, other.kind):
        return "held"
    if "failed_run" in (one.kind, other.kind):
        return "not compared: a failed run"
    if one.kind == other.kind:
        return "same"
    return "better" if one.kind == "passed" else "worse"


@dataclass(frozen=True)
class Comparison:
    arm: str
    against: str
    verdicts: tuple[str, ...]  # by repeat

    @property
    def label(self) -> str:
        return f"{ARM_NAMES[self.arm]} against {ARM_NAMES[self.against].lower()}"


@dataclass(frozen=True)
class TaskResult:
    task: Task
    role: str
    held: bool
    arms: tuple[ArmResult, ...]
    comparisons: tuple[Comparison, ...]


@dataclass(frozen=True)
class WorkflowResult:
    workflow: str
    name: str
    # Each trap task with its twin task, side by side; each book-level task alone.
    groups: tuple[tuple[TaskResult, ...], ...]


@dataclass(frozen=True)
class RunSetResult:
    """The runs under one name, and the private set's counts under the same name."""

    name: RunName
    first_date: str
    last_date: str
    columns: tuple[str, ...]  # each repeat's heading
    workflows: tuple[WorkflowResult, ...]
    public: dict[str, dict[str, dict[str, int]]]  # workflow, arm, outcome
    private: dict[str, dict[str, dict[str, int]]] | None
    # The freezes the section's regraded public runs ran under, and how many ran under each, graded and failed,
    # shown by its name; and its private runs' (`PrivateRunSet.regraded_from`).
    regraded_from: tuple[tuple[str, int, int], ...] = ()
    private_regraded_from: tuple[tuple[str, int, int], ...] = ()

    @property
    def regraded_label(self) -> str:
        def one(kind: str, freeze: str, graded: int, failed: int) -> str:
            parts: list[str] = []
            if graded:
                runs, were = ("runs", "were") if graded != 1 else ("run", "was")
                parts.append(
                    f"{graded} {kind} {runs} ran under freeze {freeze[:12]} and {were} graded again under this one, "
                    "with no new run"
                )
            if failed:
                runs, stand = ("runs", "stand") if failed != 1 else ("run", "stands")
                parts.append(f"{failed} failed {kind} {runs} of the same pass {stand} under it too, never graded")
            return "; ".join(parts)

        return "; ".join(
            [
                *(one("public", *entry) for entry in self.regraded_from),
                *(one("private", *entry) for entry in self.private_regraded_from),
            ]
        )

    @property
    def dates(self) -> str:
        return self.first_date if self.first_date == self.last_date else f"{self.first_date} to {self.last_date}"


@dataclass(frozen=True)
class PrivateRunSet:
    name: RunName
    first_date: str
    last_date: str
    counts: dict[str, dict[str, dict[str, int]]]
    # The freezes its regraded runs ran under, with how many graded and how many failed (the owner, 19 November
    # 2026: the private-only pass graded again after it ran, which the results page says).
    regraded_from: tuple[tuple[str, int, int], ...] = ()


def _date(record: dict[str, Any]) -> str:
    return str(record["started_utc"])[:10]


def _task_result(
    task: Task, role: str, arms: dict[str, dict[Column, dict[str, Any]]], columns: Sequence[Column], held: bool
) -> TaskResult:
    """Each arm's outcome in each repeat's column, a gap where that repeat's run is under another name, and the
    pairs of the same repeat (reviewers A and B, slice 13 round 1: never one arm's repeat 2 against another's 1)."""
    rows: list[ArmResult] = []
    for arm in ARM_ORDER:
        placed = arms.get(arm, {})
        mine = tuple(outcome(placed[c], held) if c in placed else None for c in columns)
        rows.append(ArmResult(arm, ARM_NAMES[arm], mine))
    by_arm = {row.arm: row for row in rows}
    comparisons = tuple(
        Comparison(a, b, tuple(compare(x, y) for x, y in zip(by_arm[a].outcomes, by_arm[b].outcomes, strict=True)))
        for a, b in COMPARED
    )
    return TaskResult(task, role, held, tuple(rows), comparisons)


def results(
    records: dict[str, list[dict[str, Any]]],
    tasks: Path,
    private: Sequence[PrivateRunSet] = (),
    statement: ReviewStatement | None = None,
) -> list[RunSetResult]:
    """The results page's sections, one per run name, from the published run records by task (`load_records`),
    the public task files and their matrix, and the private set's counts. `statement`: the review statement the book
    was built under, whose scope releases its tax tasks' verdicts."""
    placements = {p.task_id: p for p in load_matrix(tasks.parent / MATRIX).placements}
    loaded = {task_id: load_task(tasks / f"{task_id}.toml") for task_id in records}
    # A task's runs under one arm, by name: a slot's retries are followed across names, then each run that stands
    # is counted under its own, in its repeat's column.
    named: dict[RunName, dict[str, dict[str, list[dict[str, Any]]]]] = {}
    for task_id, task_records in records.items():
        if task_id not in placements:
            raise ResultsError(f"task {task_id} has runs but no place in {tasks.parent / MATRIX}")
        for arm in ARM_ORDER:
            for record in standing([r for r in task_records if r["arm"] == arm]):
                named.setdefault(run_name(record), {}).setdefault(task_id, {}).setdefault(arm, []).append(record)
    private_by_name = {p.name: p for p in private}
    sections: list[RunSetResult] = []
    for name in {*named, *private_by_name}:
        by_task = {
            task_id: {arm: _columns(runs) for arm, runs in arms.items()}
            for task_id, arms in named.get(name, {}).items()
        }
        columns = sorted({c for arms in by_task.values() for placed in arms.values() for c in placed})
        task_results = {
            task_id: _task_result(
                loaded[task_id], placements[task_id].role, arms, columns, is_held(loaded[task_id], statement)
            )
            for task_id, arms in by_task.items()
        }
        workflows: list[WorkflowResult] = []
        public = _empty_counts()
        for workflow in WORKFLOWS:
            groups: list[tuple[TaskResult, ...]] = []
            for p in (p for p in placements.values() if p.workflow == workflow):
                if p.role == "twin" and p.pair_task in task_results:
                    continue  # shown beside its trap task
                members = [p.task_id] + ([p.pair_task] if p.role == "trap" and p.pair_task else [])
                group = tuple(task_results[m] for m in members if m in task_results)
                if group:
                    groups.append(group)
            for group in groups:
                for result in group:
                    for row in result.arms:
                        counted = _counts(o for o in row.outcomes if o is not None)
                        for kind in OUTCOMES:
                            public[workflow][row.arm][kind] += counted[kind]
            if groups:
                workflows.append(WorkflowResult(workflow, WORKFLOW_NAMES[workflow], tuple(groups)))
        # The rule the private summary is held to (`private_outcomes_problems`), on the public counts too.
        released = frozenset(t.workflow for t in loaded.values() if is_reviewed(t, statement))
        held_problems = held_count_problems(f"the public runs under {name.label}", public, released)
        if held_problems:
            raise ResultsError("; ".join(held_problems))
        dates = [_date(r) for arms in by_task.values() for placed in arms.values() for r in placed.values()]
        earlier = Counter(
            (f, r["state"] == "failed")
            for arms in by_task.values()
            for placed in arms.values()
            for r in placed.values()
            if (f := ran_under(r)) is not None
        )
        regraded_from = tuple((f, earlier[(f, False)], earlier[(f, True)]) for f in sorted({f for f, _ in earlier}))
        mine = private_by_name.get(name)
        dates += [mine.first_date, mine.last_date] if mine else []
        sections.append(
            RunSetResult(
                name=name,
                first_date=min(dates),
                last_date=max(dates),
                columns=_column_labels(columns),
                workflows=tuple(workflows),
                public=public,
                private=mine.counts if mine else None,
                regraded_from=regraded_from,
                private_regraded_from=mine.regraded_from if mine else (),
            )
        )
    return sorted(sections, key=lambda s: (s.first_date, s.last_date, s.name.label, s.name.freeze or ""))


def private_outcomes(private_runs: Path, private_tasks: Path, run_ids: Iterable[str] | None = None) -> dict[str, Any]:
    """The private set's outcome counts, per run name, workflow and arm, from its unmapped run records
    (`$CASEBOOK_PRIVATE/runs/<run id>/record.json`, which also holds the public runs' unmapped records), with the
    private task files they ran (by default `$CASEBOOK_PRIVATE/tasks/`; a pass's own, reviewer B, slice 13 round 1).
    No task ID, prompt, output, household or figure. `run_ids`, when given, are the only runs counted: a pass's own,
    so a pass run again under a new freeze (the owner's option 1a, 18 November 2026) replaces the earlier one."""
    records: dict[str, list[dict[str, Any]]] = {}
    chosen = None if run_ids is None else set(run_ids)
    for path in sorted(private_runs.glob(f"*/{RECORD}")):
        if chosen is not None and path.parent.name not in chosen:
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        if is_private_task_id(str(record["task_id"])):
            require_named(record, f"private run {path.parent.name}")
            records.setdefault(str(record["task_id"]), []).append(record)
    counts: dict[RunName, dict[str, dict[str, dict[str, int]]]] = {}
    dates: dict[RunName, list[str]] = {}
    earlier: dict[RunName, Counter[tuple[str, bool]]] = {}
    for task_id, task_records in sorted(records.items()):
        task = find_task(private_tasks, task_id)
        for arm in ARM_ORDER:
            for record in standing([r for r in task_records if r["arm"] == arm]):
                name = run_name(record)
                # A public statement never names a private task, so a private tax task's verdict stays held.
                kind = outcome(record, is_held(task, None)).kind
                counts.setdefault(name, _empty_counts())[task.workflow][arm][kind] += 1
                dates.setdefault(name, []).append(_date(record))
                if (ran := ran_under(record)) is not None:
                    earlier.setdefault(name, Counter())[(ran, record["state"] == "failed")] += 1
    run_sets = [
        {
            **name.to_dict(),
            "first_date": min(dates[name]),
            "last_date": max(dates[name]),
            "counts": counts[name],
            "regraded_from": [
                {"freeze": f, "graded": c[(f, False)], "failed": c[(f, True)]} for f in sorted({f for f, _ in c})
            ]
            if (c := earlier.get(name, Counter()))
            else [],
        }
        for name in sorted(counts, key=lambda n: (min(dates[n]), n.label, n.freeze or ""))
    ]
    return {"notice": NOTICE, "run_sets": run_sets}


_HASH = re.compile(r"[0-9a-f]{64}")
_SET_FIELDS = ("tool", "version", "models", "effort", "freeze", "first_date", "last_date", "counts", "regraded_from")


def _is_date(value: Any) -> bool:
    try:
        date.fromisoformat(str(value))
    except ValueError:
        return False
    return isinstance(value, str)


def _is_regraded_from(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(e, dict)
        and sorted(e) == ["failed", "freeze", "graded"]  # pyright: ignore[reportUnknownArgumentType]
        and isinstance(e["freeze"], str)
        and _HASH.fullmatch(e["freeze"]) is not None
        and all(type(e[k]) is int and e[k] >= 0 for k in ("graded", "failed"))
        for e in value  # pyright: ignore[reportUnknownVariableType]
    )


def _set_problems(where: str, raw: Any) -> list[str]:
    if not isinstance(raw, dict) or sorted(raw) != sorted(_SET_FIELDS):  # pyright: ignore[reportUnknownArgumentType]
        return [f"{where} is not exactly {', '.join(_SET_FIELDS)}"]
    entry: dict[str, Any] = raw  # pyright: ignore[reportUnknownVariableType]
    problems: list[str] = []
    if not all(isinstance(entry[f], str) and entry[f].strip() for f in ("tool", "version", "effort")):
        problems.append(f"{where}: tool, version and effort are named")
    models = entry["models"]
    if not isinstance(models, list) or not models or not all(isinstance(m, str) and m.strip() for m in models):  # pyright: ignore[reportUnknownVariableType]
        problems.append(f"{where}: models is a list of the models reported")
    if entry["freeze"] is not None and not isinstance(entry["freeze"], str):
        problems.append(f"{where}: freeze is a hash or null")
    if not (_is_date(entry["first_date"]) and _is_date(entry["last_date"])):
        problems.append(f"{where}: first_date and last_date are dates")
    if not _is_regraded_from(entry["regraded_from"]):
        problems.append(f"{where}: regraded_from lists each earlier freeze with its graded and failed counts")
    counts = entry["counts"]
    shape = all(
        isinstance(counts, dict)
        and sorted(counts) == sorted(WORKFLOWS)  # pyright: ignore[reportUnknownArgumentType]
        and isinstance(counts[w], dict)
        and sorted(counts[w]) == sorted(ARM_ORDER)
        and isinstance(counts[w][a], dict)
        and sorted(counts[w][a]) == sorted(OUTCOMES)
        and all(type(counts[w][a][k]) is int and counts[w][a][k] >= 0 for k in OUTCOMES)
        for w in WORKFLOWS
        for a in ARM_ORDER
    )
    if not shape:
        problems.append(f"{where}: counts are whole numbers by workflow, arm and outcome, and nothing else")
    else:
        # A held workflow's passed or failed count is a verdict published before the tax review (reviewer B).
        problems += held_count_problems(where, counts)
    return problems


def private_outcomes_problems(text: str) -> list[str]:
    """What a private summary holds beyond the private set's outcome counts by run name, workflow and arm: any
    other field, a task ID or a household ID anywhere in it, or no notice."""
    problems = [f"names private task {t}" for t in sorted(set(PRIVATE_TASK_ID.findall(text)))]
    problems += [f"names household {h}" for h in sorted(set(_HOUSEHOLD.findall(text)))]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        return [*problems, f"is not JSON ({error})"]
    if not isinstance(data, dict) or sorted(data) != ["notice", "run_sets"]:  # pyright: ignore[reportUnknownArgumentType]
        return [*problems, "is not exactly a notice and a list of run sets"]
    summary: dict[str, Any] = data  # pyright: ignore[reportUnknownVariableType]
    if summary["notice"] != NOTICE:
        problems.append("lacks the notice")
    if not isinstance(summary["run_sets"], list):
        return [*problems, "run_sets is not a list"]
    sets: list[Any] = summary["run_sets"]  # pyright: ignore[reportUnknownVariableType]
    for index, entry in enumerate(sets):
        problems += _set_problems(f"run set {index + 1}", entry)
    return problems


def load_private_outcomes(path: Path) -> list[PrivateRunSet]:
    """The published private summary, refused if it holds anything but outcome counts."""
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    problems = private_outcomes_problems(text)
    if problems:
        raise PrivateOutcomesError(f"{path.name} cannot be published: {'; '.join(problems)}")
    return [
        PrivateRunSet(
            name=RunName(s["tool"], s["version"], tuple(s["models"]), s["effort"], s["freeze"]),
            first_date=s["first_date"],
            last_date=s["last_date"],
            counts=s["counts"],
            regraded_from=tuple((e["freeze"], e["graded"], e["failed"]) for e in s["regraded_from"]),
        )
        for s in json.loads(text)["run_sets"]
    ]


def write_private_outcomes(
    private_runs: Path, private_tasks: Path, published: Path, run_ids: Iterable[str] | None = None
) -> Path:
    """Write the private set's counts to `published/results/private-outcomes.json`, refused unless the summary
    and the private set's own gate (`private_set_problems`) find nothing else of the private set in it."""
    text = json_text(private_outcomes(private_runs, private_tasks, run_ids))
    problems = private_outcomes_problems(text)
    with tempfile.TemporaryDirectory() as staging:
        (Path(staging) / PRIVATE_OUTCOMES).write_text(text, encoding="utf-8")
        problems += private_set_problems(Path(staging))
        if problems:
            raise PrivateOutcomesError(f"{PRIVATE_OUTCOMES} not written: {'; '.join(problems)}")
        target = published / RESULTS_DIR / PRIVATE_OUTCOMES
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(staging) / PRIVATE_OUTCOMES, target)
    return target


def private_outcomes_path(runs: Path) -> Path:
    """Where the private summary sits beside the published run records: `published/results/`."""
    return runs.parent / RESULTS_DIR / PRIVATE_OUTCOMES
