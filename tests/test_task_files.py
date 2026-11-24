"""docs/PLAN.md, slices 9 and 10: twenty-four task files, six per workflow, each with a prompt, fixtures,
allowed tools, expected output, grader and justified conclusion; book-level fixtures; held tax keys; and the
three counts in every result."""

from datetime import date
from pathlib import Path

import pytest

from casebook.graders.common import COUNTS
from casebook.graders.follow_up import FollowUp
from casebook.graders.registry import GRADERS
from casebook.model.crm import CrmDiff
from casebook.model.files import read_manifest
from casebook.runner.config import CRM_TOOLS
from casebook.runner.session import HELD_KEYS, keys_root_for
from casebook.tasks.fixtures import load_task_fixtures
from casebook.tasks.task import BOOK, TASK_FIELDS, WORKFLOWS, load_task

from .conftest import ROOT

TASKS = ROOT / "tasks" / "public"
FILE_TOOLS = {"Read", "Glob", "Grep"}


def task_files() -> list[Path]:
    return sorted(TASKS.glob("T-*.toml"))


def test_twenty_four_task_files_six_per_workflow_each_with_every_field() -> None:
    tasks = [load_task(path) for path in task_files()]
    assert {w: sum(t.workflow == w for t in tasks) for w in WORKFLOWS} == dict.fromkeys(WORKFLOWS, 6)
    for path, task in zip(task_files(), tasks, strict=True):
        assert path.stem == task.task_id
        raw = path.read_text()
        for field in TASK_FIELDS:
            assert f"{field} =" in raw or f"[{field}]" in raw, (task.task_id, field)
        assert task.prompt.strip() and task.justified_conclusion.strip(), task.task_id
        # A follow-up task also has the CRM sandbox's tools, all of them; no other task has any.
        follow_up = GRADERS[task.grader].follow_up
        assert task.fixtures and set(task.allowed_tools) == FILE_TOOLS | (set(CRM_TOOLS) if follow_up else set())
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
    """Every tax-lot and RMD task's key, and any other task's whose key computes a tax figure, goes to
    out/keys/: an RMD (T-REC-03, 04); a Form 8606 taxable amount, the NIIT or the tax surprises (T-MTG-01 to
    04, 06); a released lot's basis or a conversion's taxable amount (T-CMP-01 to 04). The rest are published."""
    published = Path("published/keys")
    held = {load_task(p).task_id for p in task_files() if keys_root_for(load_task(p), published, None) == HELD_KEYS}
    assert Path("out/keys") == HELD_KEYS
    assert held == {
        *("T-REC-03", "T-REC-04"),
        *(f"T-TAX-0{n}" for n in range(1, 7)),
        *("T-MTG-01", "T-MTG-02", "T-MTG-03", "T-MTG-04", "T-MTG-06"),
        *("T-CMP-01", "T-CMP-02", "T-CMP-03", "T-CMP-04"),
    }


# The graders the public tasks use; the private set's own are tested on featured pairs in their own tests.
PUBLIC_GRADERS = sorted({load_task(p).grader for p in sorted(TASKS.glob("T-*.toml"))})


def test_every_registered_grader_is_used_or_tested() -> None:
    for name in sorted(set(GRADERS) - set(PUBLIC_GRADERS)):
        assert (ROOT / "tests" / f"test_grader_{name}.py").is_file(), name


@pytest.mark.parametrize("name", PUBLIC_GRADERS)
def test_every_grader_records_the_three_counts(name: str, book: Path, tmp_path: Path) -> None:
    """Even an answer with no json block gets a result with exactly the three counts."""
    path = next(p for p in task_files() if load_task(p).grader == name)
    task = load_task(path)
    key = GRADERS[name].key(book, task.household_id, task.grader_params)
    spec = GRADERS[name]
    nothing = (FollowUp(task.household_id, CrmDiff(()), None),) if spec.follow_up else ()
    result = spec.grade("no answer here", key, tmp_path, *nothing).to_dict()
    assert set(result["counts"]) == set(COUNTS)
    assert result["score"] == 0 or result["critical_fail"] is not None or not result["passed"]
