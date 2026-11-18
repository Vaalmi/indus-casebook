"""The three live runs of T-MTG-01 (16 November 2026, `claude` 2.1.304, Opus 5.5 at high), as published: each
run's answer and its CRM sandbox diff, graded again here without the jury, so a change to the key or the
grader that moves them shows. Each meets every criterion but tone. The skill arm's answer adds the two
spouses' W-2 wages from the CRM (212,000 + 186,000 = 398,000), which zeroed it until the key listed that
derivation: the owner's fabricated-figure rule (option 1, 18 November 2026,
docs/decisions/2026-11-16-fabricated-figure-rule.md) keeps the rule strict and widens a key for each honest
derivation a live run shows."""

import json
from decimal import Decimal
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


@pytest.mark.parametrize("arm", ["basic", "checklist", "skill"])
def test_each_run_meets_every_criterion_but_tone(book: Path, tmp_path: Path, arm: str) -> None:
    record = published(arm)
    assert record["grade"] is None and record["verdict_held"] is True
    grade = regrade(book, tmp_path, record)
    earned = {c["name"]: c["earned"] == c["points"] for c in grade["breakdown"]}
    assert grade["critical_fail"] is None and all(earned[name] for name in MET), grade
    assert grade["score"] == 85  # 100 less the 15 tone points no jury gave here


def test_the_skill_run_s_joint_wages_are_a_figure_the_key_lists(book: Path) -> None:
    """The owner's fabricated-figure rule, option 1: the skill run's honest sum of two W-2s, which zeroed it, is
    now in the key, and the answer states it."""
    task = find_task(TASKS, "T-MTG-01")
    key = GRADERS[task.grader].key(book, task.household_id, task.grader_params)
    wages = [f.value for f in key.computed_figures if f.label == "the household's 2025 wages, Forms W-2 box 1"]
    assert wages == [Decimal("398000.00")]
    assert "398000.00" in published("skill")["output"].replace(",", "")


@pytest.mark.parametrize("arm", ["basic", "checklist", "skill"])
def test_each_run_wrote_only_to_its_own_household(arm: str) -> None:
    diff = parse_crm_diff(published(arm)["crm_sandbox_diff"])
    assert diff.changes and not diff.outside("HH-1204")
    assert {c.change for c in diff.changes} == {"added"}
