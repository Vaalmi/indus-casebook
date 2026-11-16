"""docs/PLAN.md, slice 9: twelve task files, six per workflow, each with a prompt, fixtures, allowed tools,
expected output, grader and justified conclusion; book-level fixtures; held tax-lot and RMD keys; and the
three counts in every result."""

from datetime import date
from pathlib import Path

import pytest

from casebook.graders.common import COUNTS
from casebook.graders.registry import GRADERS
from casebook.model.files import read_manifest
from casebook.runner.session import HELD_KEYS, keys_root_for
from casebook.tasks.fixtures import load_task_fixtures
from casebook.tasks.task import BOOK, TASK_FIELDS, load_task

from .conftest import ROOT

TASKS = ROOT / "tasks" / "public"
SLICE_9 = ("reconciliation", "tax_lot_rmd")


def task_files() -> list[Path]:
    return sorted(TASKS.glob("T-*.toml"))


def test_twelve_task_files_six_per_workflow_each_with_every_field() -> None:
    tasks = [load_task(path) for path in task_files()]
    by_workflow = {w: [t.task_id for t in tasks if t.workflow == w] for w in SLICE_9}
    assert {w: len(ids) for w, ids in by_workflow.items()} == {"reconciliation": 6, "tax_lot_rmd": 6}
    for path, task in zip(task_files(), tasks, strict=True):
        assert path.stem == task.task_id
        raw = path.read_text()
        for field in TASK_FIELDS:
            assert f"{field} =" in raw or f"[{field}]" in raw, (task.task_id, field)
        assert task.prompt.strip() and task.justified_conclusion.strip(), task.task_id
        assert task.fixtures and set(task.allowed_tools) == {"Read", "Glob", "Grep"}, task.task_id
        assert "unresolved" in task.expected_output.findings, task.task_id
        assert task.grader in GRADERS, task.task_id
        # The prompt asks for the closing json block's every field by name.
        assert all(f'"{name}"' in task.prompt for name in task.expected_output.fields), task.task_id


def test_a_book_level_task_reads_every_household_each_in_its_own_folder(book: Path, tmp_path: Path) -> None:
    load_task_fixtures(book, BOOK, ("custodian", "portfolio"), date(2026, 4, 15), tmp_path)
    households = sorted(p.name for p in (tmp_path / "households").iterdir())
    assert households == sorted(h.household_id for h in read_manifest(book).households)
    for household in households:
        assert (tmp_path / "households" / household / "custodian" / "positions.csv").is_file()
        assert (tmp_path / "households" / household / "portfolio" / "household.json").is_file()
        assert not (tmp_path / "households" / household / "crm").exists()
    # Each household's rows are filtered by the cutoff, as a household task's are.
    for line in (tmp_path / "households" / "HH-4821" / "custodian" / "cash.csv").read_text().splitlines()[1:]:
        assert line.split(",")[-1] <= "2026-04-15"


def test_tax_lot_and_rmd_keys_are_held_whatever_the_keys_folder() -> None:
    """Every tax-lot and RMD task's key, and a reconciliation task's whose key computes an RMD (T-REC-03
    and T-REC-04), goes to out/keys/; the other reconciliation keys are published."""
    published = Path("published/keys")
    held = {load_task(p).task_id for p in task_files() if keys_root_for(load_task(p), published) == HELD_KEYS}
    assert Path("out/keys") == HELD_KEYS
    assert held == {"T-REC-03", "T-REC-04", "T-TAX-01", "T-TAX-02", "T-TAX-03", "T-TAX-04", "T-TAX-05", "T-TAX-06"}


@pytest.mark.parametrize("name", sorted(GRADERS))
def test_every_grader_records_the_three_counts(name: str, book: Path, tmp_path: Path) -> None:
    """Even an answer with no json block gets a result with exactly the three counts."""
    path = next(p for p in task_files() if load_task(p).grader == name)
    task = load_task(path)
    key = GRADERS[name].key(book, task.household_id, task.grader_params)
    result = GRADERS[name].grade("no answer here", key, tmp_path).to_dict()
    assert set(result["counts"]) == set(COUNTS)
    assert result["score"] == 0 or result["critical_fail"] is not None or not result["passed"]
