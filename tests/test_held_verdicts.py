"""Reviewers A and B, slice 9 round 1: a held task's verdict stays private until the tax review. Its published
run record carries no grade, and its page shows sources and outputs only, with no verdict, no failure
marking and no justified conclusion (docs/SPEC.md). A task page also renders a key that is not a fee key."""

import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from casebook.keys.billing_groups import billing_groups_key
from casebook.model.files import json_text, read_manifest
from casebook.publish.site_build import build_site
from casebook.runner.session import held, published_record
from casebook.tasks.task import find_task

from .conftest import README, ROOT

TASKS = ROOT / "tasks" / "public"
PUBLISHED = ROOT / "published" / "runs" / "T-REC-01"


def a_graded_record(task_id: str) -> dict[str, Any]:
    """A published T-REC-01 skill record, graded 100, recast as a run of another task."""
    path = sorted(PUBLISHED.glob("T-REC-01-skill-*.json"))[-1]
    record = json.loads(path.read_text())
    assert record["grade"]["passed"]
    run_id = record["run_id"].replace("T-REC-01", task_id)
    return record | {"task_id": task_id, "run_id": run_id}


@pytest.mark.parametrize("task_id", ["T-TAX-01", "T-TAX-05", "T-REC-03", "T-REC-04"])
def test_a_held_task_s_published_record_carries_no_grade(task_id: str) -> None:
    task = find_task(TASKS, task_id)
    assert held(task)
    public = published_record(task, a_graded_record(task_id))
    assert public["grade"] is None and public["verdict_held"] is True
    assert public["output"]  # the output is shown


def test_a_reconciliation_task_s_record_is_published_with_its_grade() -> None:
    task = find_task(TASKS, "T-REC-05")
    assert not held(task)
    record = a_graded_record("T-REC-05")
    assert published_record(task, record) == record


def runs_with(tmp_path: Path, record: dict[str, Any]) -> Path:
    runs = tmp_path / "runs"
    (runs / record["task_id"]).mkdir(parents=True)
    (runs / record["task_id"] / f"{record['run_id']}.json").write_text(json.dumps(record))
    return runs


def test_a_held_task_s_page_shows_no_verdict_even_from_a_graded_record(book: Path, tmp_path: Path) -> None:
    """Even a record that still carries its grade (one published before the hold) shows nothing of it."""
    runs = runs_with(tmp_path, a_graded_record("T-TAX-01"))
    build_site(book, tmp_path / "site", README, runs, TASKS, None)
    page = (tmp_path / "site" / "tasks" / "T-TAX-01.html").read_text()
    assert 'data-outcome="held"' in page and "Not scored until the tax review" in page
    for verdict in ("Passed:", "Failed:", "data-criterion", "Critical fail", 'data-section="justified-conclusion"'):
        assert verdict not in page, verdict
    assert find_task(TASKS, "T-TAX-01").justified_conclusion.strip()[:60] not in page


def test_a_book_level_reconciliation_task_s_page_renders_its_key(book: Path, tmp_path: Path) -> None:
    """Reviewer B, slice 9 round 1: the page assumed a fee key and failed on T-REC-05's."""
    runs = runs_with(tmp_path, a_graded_record("T-REC-05"))
    keys = tmp_path / "keys"
    (keys / read_manifest(book).version).mkdir(parents=True)
    key = billing_groups_key(book, date(2026, 4, 15))
    (keys / read_manifest(book).version / "T-REC-05.json").write_text(json_text(key.to_dict()))
    build_site(book, tmp_path / "site", README, runs, TASKS, keys)
    page = (tmp_path / "site" / "tasks" / "T-REC-05.html").read_text()
    assert "Households found" in page and "HH-4821" in page
    assert 'data-section="justified-conclusion"' in page
    shutil.rmtree(tmp_path / "site")


def test_the_index_builds_with_a_held_run_and_shows_no_verdict(book: Path, tmp_path: Path) -> None:
    """Reviewer A, slice 9 round 2: the index read the grade of a held run published without one."""
    task = find_task(TASKS, "T-TAX-01")
    runs = runs_with(tmp_path, published_record(task, a_graded_record("T-TAX-01")))
    build_site(book, tmp_path / "site", README, runs, TASKS, None)
    index = (tmp_path / "site" / "index.html").read_text()
    assert "not scored until the tax review" in index
    assert "passed, 100" not in index
