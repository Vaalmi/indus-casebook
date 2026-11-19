"""`casebook regrade`: a pass's public answers graded again under today's graders, with no new run and the jury's
stored votes, each record keeping its earlier grade (the owner, 18 November 2026, option 1 of
`docs/decisions/2026-11-18-fabricated-figure-false-zeros.md`); and `casebook pass --private`, the private set run
again under the new freeze (option 1a), whose counts replace the earlier pass's."""

import json
from pathlib import Path
from typing import Any

import pytest

from casebook.cli import main
from casebook.graders.jury import ToneResult
from casebook.model.files import json_text
from casebook.notice import NOTICE
from casebook.runner import full_pass
from casebook.runner.config import ARMS, SharedConfig
from casebook.runner.full_pass import Folders, load_pass, new_pass, run_ids, run_pass
from casebook.runner.record import REGRADED, RunRecordError, check_record
from casebook.runner.regrade import RegradeRefusedError, regrade_pass, regrade_record, stored_tone
from casebook.runner.run import private_root
from casebook.runner.session import grading, published_record
from casebook.site.results import (
    PrivateRunSet,
    RunName,
    load_private_outcomes,
    private_outcomes,
    private_outcomes_problems,
    ran_under,
    results,
    run_name,
)
from casebook.tasks.task import find_task

from .conftest import ROOT, StandIn
from .jury_fixtures import use_standin_jury
from .test_follow_up_run import ANSWER, SPEC, diff, follow_up_task
from .test_pass import fast_runs, freeze_record, frozen, private_tasks, public_tasks
from .test_results_page import OPUS, PRIVATE_COUNTS, record
from .test_run_session import answer_for

__all__ = ["freeze_record", "frozen"]  # fixtures this module's tests use
TASKS = ROOT / "tasks" / "public"
PRIVATE_ID = "X-" + "REC-09"


def _pass(tmp_path: Path, real_book: Path, standin_cli: StandIn) -> full_pass.Pass:
    """A finished pass of T-REC-01 and one private task, one repeat, on the stand-in CLI."""
    standin_cli.answer.write_text(answer_for(real_book))
    private_tasks(private_root() / "tasks", (PRIVATE_ID,))
    tasks = public_tasks(tmp_path / "tasks", "T-REC-01")
    folders = Folders(
        tasks, private_root() / "tasks", real_book, real_book, tmp_path / "keys", tmp_path / "published" / "runs"
    )
    done = run_pass(new_pass(folders, 1, SharedConfig()))
    assert done.state == "complete"
    return done


def _record(run_id: str) -> dict[str, Any]:
    return json.loads((private_root() / "runs" / run_id / "record.json").read_text())


def _as_if_zeroed(run_id: str) -> dict[str, Any]:
    """The run's record as the strict rule graded it: zero, for a figure the run derived."""
    path = private_root() / "runs" / run_id / "record.json"
    record = json.loads(path.read_text())
    record["grade"] = {**record["grade"], "score": 0, "passed": False, "critical_fail": "fabricated figure: x = 78"}
    record["hashes"]["grader"] = "1" * 64
    path.write_text(json.dumps(record))
    return record


def test_a_pass_s_public_answers_are_graded_again_with_their_earlier_grade_kept(
    tmp_path: Path, real_book: Path, standin_cli: StandIn, frozen: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    done = _pass(tmp_path, real_book, standin_cli)
    public = [s.runs[-1].run_id for s in done.slots if s.slot.task_id == "T-REC-01"]
    private = [s.runs[-1].run_id for s in done.slots if s.slot.task_id == PRIVATE_ID]
    zeroed = {run_id: _as_if_zeroed(run_id)["grade"] for run_id in public}
    private_before = {run_id: _record(run_id) for run_id in private}
    calls = len(standin_cli.log.read_text().splitlines())

    assert main(["regrade", done.pass_id]) == 0
    out = capsys.readouterr().out
    assert f"regraded 3 runs of pass {done.pass_id}; 3 grades changed" in out
    assert "T-REC-01 basic" in out and "0 (fabricated figure: x = 78) -> 100" in out
    assert len(standin_cli.log.read_text().splitlines()) == calls  # no run again
    for run_id in public:
        record = _record(run_id)
        assert record["grade"]["score"] == 100 and record["state"] == "graded"
        assert record[REGRADED]["grade_before"] == zeroed[run_id]
        assert record[REGRADED]["grader_before"] == "1" * 64 != record["hashes"]["grader"]
        assert record[REGRADED]["freeze"] is not None and record[REGRADED]["decision"].startswith("docs/decisions/")
        published = json.loads((tmp_path / "published" / "runs" / "T-REC-01" / f"{run_id}.json").read_text())
        assert published["grade"]["score"] == 100 and published[REGRADED]["grade_before"]["score"] == 0
        assert run_name(published).freeze == record[REGRADED]["freeze"]
    # The private set is run again under option 1a, never regraded.
    assert {run_id: _record(run_id) for run_id in private} == private_before

    # A second regrade keeps the grade the run first had, not the regrade's own.
    assert main(["regrade", done.pass_id]) == 0
    assert all(_record(run_id)[REGRADED]["grade_before"] == zeroed[run_id] for run_id in public)


def test_a_pass_s_failed_run_stands_under_the_regrade_s_freeze_never_graded(
    tmp_path: Path, real_book: Path, standin_cli: StandIn, frozen: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Found building the results page, 19 November 2026: the regrade left the pass's five failed runs under the
    # freeze they ran under, so the pass showed as two sections and, in the regraded one, its failed slots as
    # "not run" and no failed runs counted.
    standin_cli.answer.write_text(answer_for(real_book))
    real_run = full_pass.run_and_grade
    calls: list[str] = []

    def error_on_the_second(*args: Any, **named: Any) -> Any:
        calls.append(f"{args[0]} {args[1]}")
        standin_cli.set("error" if len(calls) == 2 else "answer")
        return real_run(*args, **named)

    private_tasks(private_root() / "tasks", ())
    monkeypatch.setattr(full_pass, "run_and_grade", error_on_the_second)
    tasks = public_tasks(tmp_path / "tasks", "T-REC-01")
    published = tmp_path / "published" / "runs"
    folders = Folders(tasks, private_root() / "tasks", real_book, real_book, tmp_path / "keys", published)
    done = run_pass(new_pass(folders, 1, SharedConfig()))
    [failed_id] = [s.runs[-1].run_id for s in done.slots if s.runs[-1].state == "failed"]
    for run_id in (s.runs[-1].run_id for s in done.slots if s.runs[-1].state != "failed"):
        _as_if_zeroed(run_id)

    done_list = regrade_pass(load_pass(done.pass_id))
    assert [str(r) for r in done_list if r.run_id == failed_id] == [
        f"T-REC-01 checklist: {failed_id}: failed run, never graded; stands under this freeze"
    ]
    failed = _record(failed_id)
    assert (failed["state"], failed["grade"], failed[REGRADED]["grade_before"]) == ("failed", None, None)
    records = [json.loads(p.read_text()) for p in sorted((published / "T-REC-01").glob("*[0-9a-f].json"))]
    assert {run_name(r).freeze for r in records} == {failed[REGRADED]["freeze"]}
    [section] = results({"T-REC-01": records}, TASKS, [])
    assert section.public["reconciliation"]["checklist"]["failed_run"] == 1
    # Here the pass ran under the regrade's own freeze; as if it ran under an earlier one, the section says so.
    earlier = [r | {"freeze": "a" * 64} for r in records]
    [section] = results({"T-REC-01": earlier}, TASKS, [])
    assert section.regraded_label == (
        f"2 public runs ran under freeze {'a' * 12} and were graded again under this one, with no new run; "
        "1 failed public run of the same pass stands under it too, never graded"
    )


def test_a_regrade_is_refused_unless_the_freeze_matches_today_s_hashes(
    tmp_path: Path,
    real_book: Path,
    standin_cli: StandIn,
    freeze_record: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    done = _pass(tmp_path, real_book, standin_cli)
    assert main(["regrade", done.pass_id]) == 2
    assert "regrade runs only under the recorded freeze" in capsys.readouterr().err
    assert all(REGRADED not in _record(s.runs[-1].run_id) for s in done.slots)


def test_a_regrade_is_refused_when_the_key_is_not_the_one_the_run_ran_with(
    tmp_path: Path, real_book: Path, standin_cli: StandIn, frozen: Path
) -> None:
    done = _pass(tmp_path, real_book, standin_cli)
    run_id = done.slots[0].runs[-1].run_id
    path = private_root() / "runs" / run_id / "record.json"
    record = json.loads(path.read_text())
    record["hashes"]["answer"] = "2" * 64
    path.write_text(json.dumps(record))
    with pytest.raises(RegradeRefusedError, match="not the one it ran with"):
        regrade_pass(load_pass(done.pass_id))


def test_a_follow_up_run_is_graded_again_on_its_stored_votes_without_calling_the_jury(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jury = use_standin_jury(tmp_path / "jury", monkeypatch)
    jury.set("codex", score=5)
    task = follow_up_task()
    record: dict[str, Any] = {"run_id": "r", "crm_sandbox_diff": diff("HH-4821"), "output": ANSWER}
    record["grade"] = grading(task, SPEC, None, record)(ANSWER, tmp_path)
    asked = len(jury.calls("claude"))
    jury.set("codex", mode="error")  # a jury called again would now lose a vote
    again = regrade_record(task, SPEC, None, record, tmp_path)
    assert again == record["grade"] and len(jury.calls("claude")) == asked


def test_stored_votes_are_refused_unless_they_are_on_the_message_the_answer_drafts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_standin_jury(tmp_path / "jury", monkeypatch)
    task = follow_up_task()
    record: dict[str, Any] = {"run_id": "r", "crm_sandbox_diff": diff("HH-4821")}
    grade = grading(task, SPEC, None, record)(ANSWER, tmp_path)
    assert ToneResult.from_dict(grade["tone"]).to_dict() == grade["tone"]
    other = ANSWER.replace("0001", "0002")
    with pytest.raises(RegradeRefusedError, match="not on the message"):
        stored_tone(task, other, grade)
    with pytest.raises(RegradeRefusedError, match="no votes are stored"):
        stored_tone(task, ANSWER, {**grade, "tone": None})
    with pytest.raises(RegradeRefusedError, match="drafts no message"):
        stored_tone(task, "No block.", grade)
    tampered = {**grade["tone"], "score": 1}
    with pytest.raises(RegradeRefusedError, match="cannot be read back"):
        stored_tone(task, ANSWER, {**grade, "tone": tampered})


def test_a_regraded_record_names_when_and_what_it_had_before() -> None:
    record = {
        "run_id": "r",
        **{f: None for f in ("task_id", "arm", "failure_reason", "dataset", "cli_version", "model_requested")},
        **{f: None for f in ("models_reported", "started_utc", "ended_utc", "settings", "tools_and_permissions")},
        **{f: None for f in ("instruction_loaded", "transcript", "token_use", "crm_sandbox_diff", "freeze")},
        "state": "graded",
        "hashes": dict.fromkeys(("dataset", "task", "skill", "checklist", "grader", "answer", "config"), "0"),
        "attempts": [],
        "errors": [],
        "output": "x",
        "grade": {"score": 100},
    }
    regraded = dict.fromkeys(("utc", "freeze", "decision", "grader_before", "grade_before"), "x")
    check_record({**record, REGRADED: regraded})
    with pytest.raises(RunRecordError, match="a regrade names"):
        check_record({**record, REGRADED: {"utc": "x"}})
    # A failed run of a regraded pass carries it with no grade before or after; never with one.
    failed = {**record, "state": "failed", "grade": None, "failure_reason": "CLI error"}
    check_record({**failed, REGRADED: {**regraded, "grade_before": None}})
    with pytest.raises(RunRecordError, match="a failed run is never graded"):
        check_record({**failed, REGRADED: regraded})


def test_a_held_task_s_regraded_record_is_published_without_its_earlier_grade() -> None:
    task = find_task(TASKS, "T-TAX-01")
    mapped = {"state": "mapped", "grade": {"score": 100}, REGRADED: {"freeze": "f", "grade_before": {"score": 0}}}
    public = published_record(task, mapped)
    assert public["grade"] is None and public[REGRADED] == {"freeze": "f", "grade_before": None}


def test_a_regraded_public_run_stands_beside_the_private_set_run_again_under_the_same_freeze() -> None:
    # Reviewers A (S4) and B (S3), round 1: the regraded public runs (ran under A, graded again under B) and the
    # private set run again under B were two sections, each with the other's side empty.
    first, second = "a" * 64, "b" * 64
    public = record("T-REC-01", "skill", "2026-11-18T08:10", "passed 100", freeze=first)
    public[REGRADED] = {"utc": "2026-11-19T03:00:00+00:00", "freeze": second, "decision": "d"}
    public[REGRADED] |= {"grader_before": "0" * 64, "grade_before": {"score": 0}}
    name = RunName("Claude Code", "2.1.304", (OPUS,), "high", second)
    assert run_name(public) == name and ran_under(public) == first
    private = PrivateRunSet(name, "2026-11-19", "2026-11-19", PRIVATE_COUNTS)
    [section] = results({"T-REC-01": [public]}, TASKS, [private])
    assert section.private == PRIVATE_COUNTS
    assert section.public["reconciliation"]["skill"]["passed"] == 1
    assert section.regraded_label == (
        f"1 public run ran under freeze {first[:12]} and was graded again under this one, with no new run"
    )


def test_a_regrade_is_refused_when_what_the_run_ran_is_not_today_s(
    tmp_path: Path, real_book: Path, standin_cli: StandIn, frozen: Path
) -> None:
    done = _pass(tmp_path, real_book, standin_cli)
    run_id = done.slots[0].runs[-1].run_id
    path = private_root() / "runs" / run_id / "record.json"
    record_ = json.loads(path.read_text())
    record_["hashes"]["skill"] = "3" * 64
    path.write_text(json.dumps(record_))
    with pytest.raises(RegradeRefusedError, match="its skill changed since the run"):
        regrade_pass(load_pass(done.pass_id))


# `casebook pass --private`


def test_a_private_pass_runs_the_private_set_alone_and_its_counts_replace_the_earlier_pass_s(
    tmp_path: Path, real_book: Path, standin_cli: StandIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_tasks(private_root() / "tasks", (PRIVATE_ID,))
    tasks = public_tasks(tmp_path / "tasks", "T-REC-01")
    calls, run = fast_runs(quota_at=0)
    monkeypatch.setattr(full_pass, "run_and_grade", run)
    folders = Folders(
        tasks, private_root() / "tasks", real_book, real_book, tmp_path / "keys", tmp_path / "published" / "runs"
    )
    first = run_pass(new_pass(folders, 1, SharedConfig()))
    assert len(calls) == 6
    args = ["pass", "--private", "--tasks", str(tasks), "--book", str(real_book), "--private-book", str(real_book)]
    args += ["--keys", str(tmp_path / "keys"), "--runs", str(tmp_path / "published" / "runs"), "--repeats", "1"]
    assert main(args) == 0
    assert calls[6:] == [f"{PRIVATE_ID} {arm}" for arm in ARMS]
    # The counts are the second pass's three runs alone, not the six private runs of both passes.
    summary = json.loads((tmp_path / "published" / "results" / "private-outcomes.json").read_text())
    [run_set] = summary["run_sets"]
    assert sum(sum(arm.values()) for arm in run_set["counts"]["reconciliation"].values()) == 3
    both = private_outcomes(private_root() / "runs", private_root() / "tasks")
    assert sum(sum(arm.values()) for arm in both["run_sets"][0]["counts"]["reconciliation"].values()) == 6
    mine = private_outcomes(private_root() / "runs", private_root() / "tasks", run_ids(first))
    assert sum(sum(arm.values()) for arm in mine["run_sets"][0]["counts"]["reconciliation"].values()) == 3


def test_a_private_pass_is_graded_again_its_counts_saying_so_and_nothing_of_it_published(
    tmp_path: Path, real_book: Path, standin_cli: StandIn, frozen: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The owner, 19 November 2026 (`docs/decisions/2026-11-19-billing-group-totals.md`): both passes graded
    # again, the private-only one too, and the results page says its grader changed after it ran.
    standin_cli.answer.write_text(answer_for(real_book))
    private_tasks(private_root() / "tasks", (PRIVATE_ID,))
    tasks = public_tasks(tmp_path / "tasks", "T-REC-01")
    published = tmp_path / "published" / "runs"
    folders = Folders(tasks, private_root() / "tasks", real_book, real_book, tmp_path / "keys", published)
    done = run_pass(new_pass(folders, 1, SharedConfig(), private_only=True))
    ids = [s.runs[-1].run_id for s in done.slots]
    earlier = "a" * 64
    for run_id in ids:
        path = private_root() / "runs" / run_id / "record.json"
        path.write_text(json.dumps(_as_if_zeroed(run_id) | {"freeze": earlier}))
    assert main(["regrade", done.pass_id]) == 0
    out = capsys.readouterr().out
    assert f"regraded 3 runs of pass {done.pass_id}; 3 grades changed" in out and "private outcome counts:" in out
    for run_id in ids:
        record = _record(run_id)
        assert record["grade"]["score"] == 100 and record[REGRADED]["grade_before"]["score"] == 0
    assert not published.exists() or not any(published.rglob(f"{PRIVATE_ID}*"))
    summary = json.loads((tmp_path / "published" / "results" / "private-outcomes.json").read_text())
    [run_set] = summary["run_sets"]
    assert run_set["regraded_from"] == [{"freeze": earlier, "graded": 3, "failed": 0}]
    [loaded] = load_private_outcomes(tmp_path / "published" / "results" / "private-outcomes.json")
    assert loaded.regraded_from == ((earlier, 3, 0),)
    [section] = results({}, TASKS, [loaded])
    assert section.regraded_label == (
        f"3 private runs ran under freeze {earlier[:12]} and were graded again under this one, with no new run"
    )


def test_a_full_pass_s_private_slots_are_never_regraded(
    tmp_path: Path, real_book: Path, standin_cli: StandIn, frozen: Path
) -> None:
    done = _pass(tmp_path, real_book, standin_cli)
    assert {r.slot.split()[0] for r in regrade_pass(load_pass(done.pass_id))} == {"T-REC-01"}


@pytest.mark.parametrize(
    "regraded_from",
    [None, [{"freeze": "x", "graded": 1, "failed": 0}], [{"freeze": "a" * 64, "graded": -1, "failed": 0}]],
)
def test_a_private_summary_s_regrade_note_is_only_freezes_and_counts(regraded_from: Any) -> None:
    summary: dict[str, Any] = {"notice": NOTICE}
    entry = {"tool": "Claude Code", "version": "2.1.304", "models": [OPUS], "effort": "high", "freeze": "b" * 64}
    entry |= {"first_date": "2026-11-19", "last_date": "2026-11-19", "counts": PRIVATE_COUNTS}
    summary["run_sets"] = [entry | {"regraded_from": regraded_from}]
    assert any("regraded_from" in p for p in private_outcomes_problems(json_text(summary)))


def test_a_private_pass_is_new_never_a_resume(standin_cli: StandIn, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["pass", "--private", "--resume", "pass-20261118T080940Z-4471"]) == 2
    assert "--private starts a new pass" in capsys.readouterr().err
