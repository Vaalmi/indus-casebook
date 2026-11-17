"""The three live runs of T-MTG-01 (16 November 2026, `claude` 2.1.304, Opus 5.5 at high), as published: each
run's answer and its CRM sandbox diff, graded again here without the jury, so a change to the key or the
grader that moves them shows. Basic and checklist meet every criterion but tone; the skill arm's answer adds
the two spouses' W-2 wages from the CRM (212,000 + 186,000 = 398,000), a derivation the key does not list,
which the strict fabricated-figure rule zeroes (the owner's open decision,
docs/decisions/2026-11-16-fabricated-figure-rule.md)."""

import json
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.follow_up import FollowUp
from casebook.graders.registry import GRADERS
from casebook.model.crm import parse_crm_diff
from casebook.tasks.fixtures import load_task_fixtures
from casebook.tasks.task import find_task

from .conftest import ROOT

TASKS = ROOT / "tasks" / "public"
RUNS = ROOT / "published" / "runs" / "T-MTG-01"
MET = ("output_parses", "finding", "taxable_amount", "basis_carried", "follow_up")


def published(arm: str) -> dict[str, Any]:
    (path,) = sorted(RUNS.glob(f"T-MTG-01-{arm}-*[0-9a-f].json"))
    return json.loads(path.read_text())


def regrade(book: Path, tmp_path: Path, record: dict[str, Any]) -> dict[str, Any]:
    task = find_task(TASKS, "T-MTG-01")
    spec = GRADERS[task.grader]
    load_task_fixtures(book, task.household_id, task.fixtures, task.cutoff, tmp_path)
    key = spec.key(book, task.household_id, task.grader_params)
    follow_up = FollowUp(task.household_id, parse_crm_diff(record["crm_sandbox_diff"]), None)
    return spec.grade(record["output"], key, tmp_path, follow_up).to_dict()


@pytest.mark.parametrize("arm", ["basic", "checklist"])
def test_the_basic_and_checklist_runs_meet_every_criterion_but_tone(book: Path, tmp_path: Path, arm: str) -> None:
    record = published(arm)
    assert record["grade"] is None and record["verdict_held"] is True
    grade = regrade(book, tmp_path, record)
    earned = {c["name"]: c["earned"] == c["points"] for c in grade["breakdown"]}
    assert grade["critical_fail"] is None and all(earned[name] for name in MET), grade
    assert grade["score"] == 85  # 100 less the 15 tone points no jury gave here


def test_the_skill_run_is_zeroed_for_a_sum_the_key_does_not_list(book: Path, tmp_path: Path) -> None:
    grade = regrade(book, tmp_path, published("skill"))
    assert grade["score"] == 0
    assert grade["critical_fail"].startswith("fabricated figure: Combined 2025 W-2 wages")
    assert "398000.00" in grade["critical_fail"]
    assert all(c["earned"] == c["points"] for c in grade["breakdown"] if c["name"] in MET)


@pytest.mark.parametrize("arm", ["basic", "checklist", "skill"])
def test_each_run_wrote_only_to_its_own_household(arm: str) -> None:
    diff = parse_crm_diff(published(arm)["crm_sandbox_diff"])
    assert diff.changes and not diff.outside("HH-1204")
    assert {c.change for c in diff.changes} == {"added"}
