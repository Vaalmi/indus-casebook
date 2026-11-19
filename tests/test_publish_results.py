"""docs/PLAN.md, slice 13: a result with tool, version, model or date missing cannot be published; published run
records show aliases only, unmapped records exist only under `$CASEBOOK_PRIVATE`, and no prompt, output or run
record of a private task is in the published files; the private set publishes its outcome counts and nothing else."""

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from casebook.model.files import json_text
from casebook.notice import NOTICE
from casebook.publish.gates import real_identifier_problems, run_layout_problems, unmapped_record_problems
from casebook.publish.private_set import private_households, private_set_problems
from casebook.publish.site_build import SiteBuildError, build_site
from casebook.site.results import (
    PrivateOutcomesError,
    load_private_outcomes,
    private_outcomes,
    private_outcomes_path,
    private_outcomes_problems,
    write_private_outcomes,
)
from casebook.site.tasks import UnnamedResultError, load_records, require_named

from .conftest import README, ROOT
from .test_results_page import FREEZE, OPUS, TASKS, no_counts, record

PUBLISHED = ROOT / "published"
# Private task IDs, built so that no public file states one.
PRIVATE_REC = "X-" + "REC-09"
PRIVATE_TAX = "X-" + "TAX-09"


def a_private_household() -> str:
    return sorted(private_households())[0]


def write_runs(folder: Path, *records: dict[str, Any]) -> Path:
    runs = folder / "runs"
    for rec in records:
        (runs / rec["task_id"]).mkdir(parents=True, exist_ok=True)
        (runs / rec["task_id"] / f"{rec['run_id']}.json").write_text(json.dumps(rec))
    return runs


def build(book: Path, folder: Path, runs: Path) -> int:
    return build_site(book, folder / "site", README, runs, TASKS, None)


# A result named but for one of the four.
UNNAMED: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "the tool (cli_version)": lambda r: r | {"cli_version": "2.1.304"},
    "the version (cli_version)": lambda r: r | {"cli_version": "unknown (Claude Code)"},
    "models_reported": lambda r: r | {"models_reported": []},
    "started_utc": lambda r: r | {"started_utc": ""},
}


@pytest.mark.parametrize("missing", list(UNNAMED))
def test_a_result_without_its_tool_version_model_or_date_cannot_be_published(
    missing: str, book: Path, tmp_path: Path
) -> None:
    named = record("T-REC-01", "skill", "2026-11-18T10:00", "passed 100")
    runs = write_runs(tmp_path, record("T-REC-01", "basic", "2026-11-18T10:01", "failed 40"), UNNAMED[missing](named))
    with pytest.raises(UnnamedResultError, match=re.escape(f"lacks {missing}, so it cannot be published")):
        build(book, tmp_path, runs)
    assert not (tmp_path / "site").exists()


def test_a_named_result_and_an_unnamed_failed_run_are_published(book: Path, tmp_path: Path) -> None:
    """A failed run is never scored, and its CLI may not have started to name itself."""
    failed = record("T-REC-01", "basic", "2026-11-18T10:01", "run the CLI could not start")
    failed |= {"cli_version": "unknown (FileNotFoundError: claude)", "models_reported": []}
    runs = write_runs(tmp_path, record("T-REC-01", "skill", "2026-11-18T10:00", "passed 100"), failed)
    build(book, tmp_path, runs)
    page = (tmp_path / "site" / "results.html").read_text()
    assert "Claude Code 2.1.304 · model claude-opus-5-5" in page
    assert "failed run: the CLI could not start" in page


@pytest.mark.parametrize("models", [[""], ["   "], [], OPUS, None], ids=repr)
def test_a_model_named_blank_or_not_as_a_list_is_no_model(models: Any, book: Path, tmp_path: Path) -> None:
    """Reviewers A and B, slice 13 round 1: `models_reported` of `[""]` or `["   "]` was taken as named, and the
    result published with no model."""
    unnamed = a_run(models_reported=models)
    with pytest.raises(UnnamedResultError, match="lacks models_reported, so it cannot be published"):
        require_named(unnamed, "the run")
    runs = write_runs(tmp_path, record("T-REC-01", "basic", "2026-11-18T10:01", "failed 40"), unnamed)
    with pytest.raises(UnnamedResultError, match="lacks models_reported"):
        build(book, tmp_path, runs)
    assert not (tmp_path / "site").exists()


def test_a_tool_named_blank_is_no_tool() -> None:
    """Reviewers A and B, slice 13 round 1: the tool and the version are named, not blank."""
    with pytest.raises(UnnamedResultError, match=re.escape("lacks the tool (cli_version), so")):
        require_named(a_run(cli_version="2.1.304 (   )"), "the run")
    with pytest.raises(UnnamedResultError, match=re.escape("lacks the tool (cli_version), the version (cli_version)")):
        require_named(a_run(cli_version="   "), "the run")


@pytest.mark.parametrize("where", ["at the top", "a folder deeper"])
def test_a_run_record_outside_its_task_folder_is_checked_and_its_layout_refused(
    where: str, book: Path, tmp_path: Path
) -> None:
    """Reviewer A, slice 13 round 1: the naming and unmapped gates read only `<task>/<file>.json`, while the site
    copies every file under the runs folder, so a record directly under it, or a folder deeper, was published
    unchecked. Every record is now read at any depth, and the site build refuses any file but a run's record or
    transcript at `<task>/<run id>`."""
    runs = write_runs(tmp_path, a_run())
    stray = a_run(models_reported=[], state="graded")
    folder = runs if where == "at the top" else runs / "T-REC-01" / "older"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stray['run_id']}.json"
    path.write_text(json.dumps(stray))
    relative = path.relative_to(runs).as_posix()
    assert run_layout_problems(runs) == [f"{relative}: not <task>/<run id>.json or <task>/<run id>.transcript.jsonl"]
    assert [p.split(":")[0] for p in unmapped_record_problems(runs)] == [relative]
    with pytest.raises(UnnamedResultError, match=re.escape(f"{relative} lacks models_reported")):
        load_records(runs)
    with pytest.raises(SiteBuildError, match=re.escape(f"files outside the runs' layout:\n  {relative}: not <task>")):
        build(book, tmp_path, runs)
    assert not (tmp_path / "site").exists()


def test_a_held_workflow_s_verdict_count_is_refused_in_the_private_summary(tmp_path: Path) -> None:
    """Reviewer B, slice 13 round 1: a summary counting `tax_lot_rmd.skill.passed = 1` passed the check and was shown
    on the page; a tax-lot and RMD outcome is held until the tax review."""
    summary = _summary_with({})
    summary["run_sets"][0]["counts"]["tax_lot_rmd"]["skill"]["passed"] = 1
    text = json_text(summary)
    assert private_outcomes_problems(text) == ["run set 1: tax_lot_rmd skill counts 1 passed, but it is held"]
    path = tmp_path / "results" / "private-outcomes.json"
    path.parent.mkdir()
    path.write_text(text)
    with pytest.raises(PrivateOutcomesError, match="tax_lot_rmd skill counts 1 passed, but it is held"):
        load_private_outcomes(path)
    summary["run_sets"][0]["counts"]["tax_lot_rmd"]["skill"] = {"passed": 0, "failed": 0, "failed_run": 0, "held": 3}
    assert private_outcomes_problems(json_text(summary)) == []


def _summary_with(extra: dict[str, Any]) -> dict[str, Any]:
    counts = no_counts()
    run_set = {"tool": "Claude Code", "version": "2.1.304", "models": [OPUS], "effort": "high", "freeze": FREEZE}
    run_set |= {"first_date": "2026-11-18", "last_date": "2026-11-18", "counts": counts, "regraded_from": []}
    return {"notice": NOTICE, "run_sets": [run_set | extra]}


def _private_summary(folder: Path, extra: dict[str, Any]) -> None:
    (folder / "results").mkdir()
    (folder / "results" / "private-outcomes.json").write_text(json_text(_summary_with(extra)))


def a_run(**changes: Any) -> dict[str, Any]:
    return record("T-REC-01", "skill", "2026-11-18T10:00", "passed 100") | changes


# Each kind of thing the published folder must never hold, and the site build's refusal of it.
VIOLATIONS: dict[str, tuple[Callable[[Path], Path], str]] = {
    "an unmapped run record": (
        lambda f: write_runs(f, a_run(state="graded")),
        r"unmapped run records:\n  T-REC-01/T-REC-01-skill-\S+\.json: an unmapped run record \(state 'graded'\)",
    ),
    "a real ticker in a run record": (
        lambda f: write_runs(f, a_run(output="Sell the MSFT lot")),
        r"real ticker 'MSFT'",
    ),
    "a private task's run record": (
        lambda f: write_runs(f, a_run(task_id=PRIVATE_REC)),
        rf"it is private task {PRIVATE_REC}'s \(its task_id\)",
    ),
    "a private task's run folder": (
        lambda f: write_runs(f, a_run(run_id=f"{PRIVATE_REC}-skill-20261118T1000Z-0001")),
        rf"its path names private task {PRIVATE_REC}",
    ),
    "a private task's output in a public transcript": (
        lambda f: _with_transcript(f, {"type": "result", "task_id": PRIVATE_TAX, "result": "the private answer"}),
        rf"it is private task {PRIVATE_TAX}'s",
    ),
    "a private task in the private summary": (
        lambda f: _with_summary(f, {"task_id": PRIVATE_REC}),
        rf"private task {PRIVATE_REC}",
    ),
    "a private pair's household in the private summary": (
        lambda f: _with_summary(f, {"models": [a_private_household()]}),
        rf"names household {a_private_household()}",
    ),
}


def _with_transcript(folder: Path, line: dict[str, Any]) -> Path:
    rec = a_run()
    runs = write_runs(folder, rec)
    (runs / "T-REC-01" / f"{rec['run_id']}.transcript.jsonl").write_text(json.dumps(line) + "\n")
    return runs


def _with_summary(folder: Path, extra: dict[str, Any]) -> Path:
    runs = write_runs(folder, a_run())
    _private_summary(folder, extra)
    return runs


@pytest.mark.parametrize("violation", list(VIOLATIONS))
def test_the_site_build_refuses_each_kind_of_violation_in_the_published_folder(
    violation: str, book: Path, tmp_path: Path
) -> None:
    seed, refusal = VIOLATIONS[violation]
    runs = seed(tmp_path)
    with pytest.raises(SiteBuildError, match=refusal):
        build(book, tmp_path, runs)
    assert not (tmp_path / "site").exists()


def test_the_real_published_folder_passes_the_gates() -> None:
    runs = PUBLISHED / "runs"
    assert private_set_problems(PUBLISHED) == []
    assert real_identifier_problems(PUBLISHED) == []
    assert unmapped_record_problems(runs) == [] and run_layout_problems(runs) == []
    assert all(r["task_id"].startswith("T-") for rs in load_records(runs).values() for r in rs)  # each named
    load_private_outcomes(private_outcomes_path(runs))  # absent until the pass, or counts only


def private_task(tasks: Path, task_id: str, public: str) -> None:
    tasks.mkdir(parents=True, exist_ok=True)
    text = (TASKS / f"{public}.toml").read_text().replace(f'task_id = "{public}"', f'task_id = "{task_id}"')
    (tasks / f"{task_id}.toml").write_text(text)


def private_runs(private: Path, *records: dict[str, Any]) -> Path:
    """Unmapped run records as `casebook run` keeps them: `$CASEBOOK_PRIVATE/runs/<run id>/record.json`."""
    runs = private / "runs"
    for rec in records:
        (runs / rec["run_id"]).mkdir(parents=True)
        (runs / rec["run_id"] / "record.json").write_text(json.dumps(rec))
    return runs


def graded(rec: dict[str, Any]) -> dict[str, Any]:
    """A private run's record is never mapped: it stops at graded."""
    return rec if rec["state"] == "failed" else rec | {"state": "graded"}


@pytest.fixture
def private(tmp_path: Path) -> Path:
    private = tmp_path / "private"
    private_task(private / "tasks", PRIVATE_REC, "T-REC-01")
    private_task(private / "tasks", PRIVATE_TAX, "T-TAX-01")
    return private


def test_the_private_summary_counts_each_slot_s_outcome_by_workflow_and_arm(private: Path, tmp_path: Path) -> None:
    timed_out = graded(record(PRIVATE_REC, "skill", "2026-11-18T10:02", "run timeout"))
    retry = graded(record(PRIVATE_REC, "skill", "2026-11-19T08:00", "passed 100"))
    runs = private_runs(
        private,
        graded(record(PRIVATE_REC, "basic", "2026-11-18T10:00", "failed 40")),
        graded(record(PRIVATE_REC, "checklist", "2026-11-18T10:01", "passed 100")),
        timed_out,
        retry | {"retries": [{"run_id": timed_out["run_id"], "failure_reason": "timeout"}]},
        # A held task's grade, kept in the private record, is counted as held.
        graded(record(PRIVATE_TAX, "checklist", "2026-11-18T10:03", "passed 100")),
        graded(record(PRIVATE_TAX, "skill", "2026-11-18T10:04", "run quota")),
        # A public run's unmapped record sits in the same folder, and is not the private set's.
        graded(record("T-REC-01", "basic", "2026-11-18T10:05", "failed 40")),
    )
    expected = no_counts()
    expected["reconciliation"]["basic"]["failed"] = 1
    expected["reconciliation"]["checklist"]["passed"] = 1
    expected["reconciliation"]["skill"]["passed"] = 1
    expected["tax_lot_rmd"]["checklist"]["held"] = 1
    expected["tax_lot_rmd"]["skill"]["held"] = 1
    summary = private_outcomes(runs, private / "tasks")
    assert summary == {
        "notice": NOTICE,
        "run_sets": [
            {
                "tool": "Claude Code",
                "version": "2.1.304",
                "models": [OPUS],
                "effort": "high",
                "freeze": FREEZE,
                "first_date": "2026-11-18",
                "last_date": "2026-11-19",
                "counts": expected,
                "regraded_from": [],
            }
        ],
    }
    written = write_private_outcomes(runs, private / "tasks", tmp_path / "published")
    assert written == tmp_path / "published" / "results" / "private-outcomes.json"
    text = written.read_text()
    assert json.loads(text) == summary
    assert private_outcomes_problems(text) == [] and private_set_problems(written.parent) == []
    assert not re.search(r"X-[A-Z]{3}-\d\d|HH-\d{4}|T-REC", text)
    for word in ("prompt", "output", "task_id", "household"):
        assert word not in text


def test_an_unnamed_private_result_is_not_counted(private: Path, tmp_path: Path) -> None:
    unnamed = graded(record(PRIVATE_REC, "basic", "2026-11-18T10:00", "failed 40")) | {"models_reported": []}
    runs = private_runs(private, unnamed)
    with pytest.raises(UnnamedResultError, match="lacks models_reported"):
        write_private_outcomes(runs, private / "tasks", tmp_path / "published")
    assert not (tmp_path / "published").exists()


def test_a_summary_naming_a_private_pair_s_household_is_not_written(private: Path, tmp_path: Path) -> None:
    household = a_private_household()
    runs = private_runs(private, graded(record(PRIVATE_REC, "basic", "2026-11-18T10:00", "failed 40", model=household)))
    with pytest.raises(PrivateOutcomesError, match=f"names household {household}"):
        write_private_outcomes(runs, private / "tasks", tmp_path / "published")
    assert not (tmp_path / "published").exists()


@pytest.mark.parametrize(
    ("extra", "gate"),
    [
        ({"task_id": PRIVATE_REC}, f"it is private task {PRIVATE_REC}'s"),
        ({"household_id": "?"}, "it is private pair household"),
    ],
)
def test_a_summary_with_a_private_task_or_household_is_refused_by_both_gates(
    extra: dict[str, Any], gate: str, tmp_path: Path
) -> None:
    extra = {k: a_private_household() if v == "?" else v for k, v in extra.items()}
    summary = _summary_with({})
    summary |= extra  # at the top, where the private set's own gate reads a task_id or household_id
    path = tmp_path / "results" / "private-outcomes.json"
    path.parent.mkdir()
    path.write_text(json_text(summary))
    with pytest.raises(PrivateOutcomesError, match="cannot be published"):
        load_private_outcomes(path)
    assert any(gate in p for p in private_set_problems(path.parent))
