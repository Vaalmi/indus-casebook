"""A follow-up task's run on the stand-in CLI (docs/PLAN.md, slice 10): the CRM sandbox is seeded outside the
workspace with every household's CRM as of the cutoff, reached over MCP with its tools pre-approved, and its
diff goes in the run record; the grade reads that diff and keeps every tone vote."""

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.common import COUNTS, Grade, grade_from
from casebook.graders.follow_up import TONE, FollowUp, critical, tone_criterion
from casebook.graders.registry import GraderSpec
from casebook.model.files import CRM_JSON, read_manifest
from casebook.runner.cli import arguments
from casebook.runner.config import CRM_TOOLS, SharedConfig
from casebook.runner.run import GradeRefusedError, RunInputs, ToolsMismatchError, private_root, run_task
from casebook.runner.session import grading
from casebook.tasks.task import Task, find_task

from .conftest import ROOT, StandIn
from .jury_fixtures import use_standin_jury
from .test_pass import freeze_record, frozen

TASKS = ROOT / "tasks" / "public"
FAST = SharedConfig(timeout_seconds=30, retries=0)
DAY = {"household_id": "HH-4821", "date": "2026-04-15"}
WRITES = [
    {"tool": "add_note", "arguments": {**DAY, "text": "Discussed the fee refund."}},
    {
        "tool": "add_activity",
        "arguments": {**DAY, "kind": "task", "summary": "Send the refund.", "sent_to_client": False},
    },
]


def follow_up_task(tools: tuple[str, ...] = CRM_TOOLS) -> Task:
    """T-REC-01 as if it were a follow-up task: its file tools and the sandbox's."""
    task = find_task(TASKS, "T-REC-01")
    return dataclasses.replace(task, allowed_tools=(*task.allowed_tools, *tools))


def use_follow_up(cli: StandIn, writes: list[dict[str, Any]]) -> None:
    settings = {"mode": "follow_up", "log": str(cli.log), "answer": str(cli.answer), "crm_writes": writes}
    cli.config.write_text(json.dumps(settings | {"skill": "reconciliation-as-of"}))


def run(book: Path, task: Task) -> dict[str, Any]:
    return run_task(RunInputs(task, "skill", book, None, "grader-sha", "key-sha"), FAST, private_root())


def value(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


__all__ = ["freeze_record", "frozen"]  # fixtures: a freeze recorded on today's bytes, never the published one


def test_a_follow_up_run_reaches_the_sandbox_and_records_its_diff(
    real_book: Path, standin_cli: StandIn, frozen: Path
) -> None:
    use_follow_up(standin_cli, WRITES)
    record = run(real_book, follow_up_task())
    assert record["state"] == "completed", record["errors"]
    args = record["tools_and_permissions"]["arguments"]
    assert value(args, "--tools") == "Read,Glob,Grep,Skill"
    assert value(args, "--allowedTools") == ",".join(CRM_TOOLS)
    assert "--strict-mcp-config" in args
    folder = private_root() / "runs" / record["run_id"]
    assert Path(value(args, "--mcp-config")) == (folder / "crm-1" / "mcp.json").resolve()
    assert record["settings"]["crm_tools"] == list(CRM_TOOLS)
    added = record["crm_sandbox_diff"]["households"]["HH-4821"]["added"]
    assert [(c["collection"], c["record_id"]) for c in added] == [("notes", "SB-4821-01"), ("activities", "SB-4821-02")]
    assert added[0]["after"]["text"] == "Discussed the fee refund."
    assert list(record["crm_sandbox_diff"]["households"]) == ["HH-4821"]


def test_the_sandbox_holds_every_household_as_of_the_cutoff_outside_the_workspace(
    real_book: Path, standin_cli: StandIn, frozen: Path
) -> None:
    use_follow_up(standin_cli, [])
    record = run(real_book, follow_up_task())
    folder = private_root() / "runs" / record["run_id"]
    state = json.loads((folder / "crm-1" / "state.json").read_text())
    assert sorted(state["households"]) == sorted(h.household_id for h in read_manifest(real_book).households)
    # The task's own household reads exactly as its workspace's filtered CRM does.
    workspace_crm = json.loads((folder / "workspace-1" / CRM_JSON).read_text())
    assert state["households"]["HH-4821"] == workspace_crm
    assert not any((folder / "workspace-1").rglob("state.json"))
    assert record["crm_sandbox_diff"] == {"households": {}}


def test_a_task_without_the_sandbox_gets_no_server_and_no_diff(real_book: Path, standin_cli: StandIn) -> None:
    record = run(real_book, find_task(TASKS, "T-REC-01"))
    args = record["tools_and_permissions"]["arguments"]
    assert "--mcp-config" not in args and "--allowedTools" not in args
    assert record["crm_sandbox_diff"] is None and record["settings"]["crm_tools"] == []


def test_a_task_allowing_another_mcp_tool_is_refused(real_book: Path, standin_cli: StandIn) -> None:
    with pytest.raises(ToolsMismatchError):
        run(real_book, follow_up_task((*CRM_TOOLS, "mcp__mail__send")))


def test_the_sandbox_s_tools_need_its_config() -> None:
    with pytest.raises(ValueError, match="MCP config"):
        arguments("prompt", "basic", SharedConfig(crm_tools=CRM_TOOLS))


def fake_grade(output: str, key: Any, fixtures: Path, follow_up: FollowUp) -> Grade:
    criterion, essential = tone_criterion(follow_up.tone)
    results = [("answer", 85, True, "right"), criterion]
    return grade_from(results, critical(output, follow_up), dict.fromkeys(COUNTS, 0), [TONE] if essential else [])


SPEC = GraderSpec("fake", lambda book, household, params: None, fake_grade, (), follow_up=True)
ANSWER = 'Done.\n```json\n{"client_message": "The refund is on its way to the account ending 0001."}\n```\n'


def diff(*households: str) -> dict[str, Any]:
    note = {"collection": "notes", "record_id": "SB-1", "after": {"note_id": "SB-1", "date": "2026-04-15", "text": "x"}}
    return {"households": {h: {"added": [note], "changed": [], "removed": []} for h in households}}


def test_a_follow_up_grade_keeps_every_vote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jury = use_standin_jury(tmp_path / "jury", monkeypatch)
    jury.set("codex", score=5)
    graded = grading(follow_up_task(), SPEC, None, {"run_id": "r", "crm_sandbox_diff": diff("HH-4821")})(
        ANSWER, tmp_path
    )
    assert graded["tone"]["score"] == 4 and [v["score"] for v in graded["tone"]["votes"]] == [4, 5, 4]
    assert graded["score"] == 85 + 11 and graded["passed"]
    assert "the account ending 0001" in jury.calls("claude")[0]["stdin"]


def test_a_follow_up_grade_with_a_missing_vote_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jury = use_standin_jury(tmp_path / "jury", monkeypatch)
    jury.set("agy", mode="error")
    graded = grading(follow_up_task(), SPEC, None, {"run_id": "r", "crm_sandbox_diff": diff("HH-4821")})(
        ANSWER, tmp_path
    )
    assert graded["tone"]["missing"] == ["carbon"] and graded["score"] == 85 and not graded["passed"]


def test_a_write_to_another_household_in_the_stored_diff_scores_zero(tmp_path: Path) -> None:
    record = {"run_id": "r", "crm_sandbox_diff": diff("HH-4821", "HH-1204")}
    graded = grading(follow_up_task(), SPEC, None, record)(ANSWER, tmp_path)
    assert graded["score"] == 0 and graded["critical_fail"].startswith("wrote to another household's CRM: HH-1204")


def test_a_follow_up_run_with_no_diff_is_not_graded(tmp_path: Path) -> None:
    with pytest.raises(GradeRefusedError, match="no CRM sandbox diff"):
        grading(follow_up_task(), SPEC, None, {"run_id": "r", "crm_sandbox_diff": None})(ANSWER, tmp_path)


def test_no_client_message_means_no_jury_and_no_tone(tmp_path: Path) -> None:
    graded = grading(follow_up_task(), SPEC, None, {"run_id": "r", "crm_sandbox_diff": diff("HH-4821")})(
        "No block.", tmp_path
    )
    assert graded["tone"] is None and graded["score"] == 85 and not graded["passed"]
