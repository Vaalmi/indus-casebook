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
from casebook.publish.site_build import SiteBuildError, build_site
from casebook.runner.session import held, published_record
from casebook.tasks.task import find_task

from .conftest import README, ROOT

TASKS = ROOT / "tasks" / "public"
PUBLISHED = ROOT / "published" / "runs" / "T-REC-01"


def a_graded_record(task_id: str) -> dict[str, Any]:
    """A published T-REC-01 skill record, graded 100, recast as a run of another task."""
    path = PUBLISHED / "T-REC-01-skill-20261116T135933Z-4321.json"  # slice 2's, by name: the pass adds runs
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
    """Even a record that still carries its grade (one published before the hold) shows nothing of it on the page,
    and the site build refuses to publish the record itself (slice 14's gate)."""
    from casebook.site import render_site

    runs = runs_with(tmp_path, a_graded_record("T-TAX-01"))
    with pytest.raises(SiteBuildError, match="a held task's run record carries its grade"):
        build_site(book, tmp_path / "site", README, runs, TASKS, None)
    page = render_site(book, runs, TASKS, None)["tasks/T-TAX-01.html"]
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


# The gate on a held task's page (slice 14): a page or a run record that carries a verdict, a failure marking or an
# explanation of the expected output fails the site build.
CONCLUSION = "Teodoro Villanueva, born 1952-03-14, reaches the RMD age of 73 in 2025, so his 401(k) RMD was missed."
CLEAN = (
    '<main><p data-section="sources">Sources: the household\'s files in custodian.</p>'
    '<pre class="prompt">Say whether it passed: 3 checks of 100 marked ✓.</pre>'
    '<p class="held" data-outcome="held">Not scored until the tax review: this page shows the output only.</p>'
    '<pre class="output">✓ Passed: 100 of 100. The justified conclusion: ' + CONCLUSION + "</pre>"
    '<details data-section="crm-diff"><li>Failed: 0</li></details></main>'
)


def a_held_site(tmp_path: Path, page: str, record: dict[str, Any] | None = None) -> Path:
    site = tmp_path / "site"
    (site / "tasks").mkdir(parents=True)
    (site / "tasks" / "T-TAX-01.html").write_text(page)
    if record is not None:
        (site / "data" / "runs" / "T-TAX-01").mkdir(parents=True)
        (site / "data" / "runs" / "T-TAX-01" / "T-TAX-01-basic-x.json").write_text(json.dumps(record))
    return site


def test_a_held_page_quoting_a_verdict_only_in_the_prompt_output_or_crm_passes_the_gate(tmp_path: Path) -> None:
    from casebook.publish.gates import held_page_problems

    site = a_held_site(tmp_path, CLEAN, {"grade": None, "regraded": {"grade_before": None}})
    assert held_page_problems(site, {"T-TAX-01": CONCLUSION}) == []


@pytest.mark.parametrize(
    ("added", "problem"),
    [
        ('<p class="passed" data-outcome="passed">Passed: 100 of 100</p>', "shows a verdict"),
        ("<p>Failed: 40 of 100</p>", "shows a verdict"),
        ("<p>Critical fail, scored zero</p>", "shows a verdict"),
        ("<p data-regraded>Graded again on 2026-11-19</p>", "shows a verdict"),
        ('<tr class="miss" data-criterion="finding"><td>finding</td></tr>', "marks a failure"),
        ("<td>✗ finding</td>", "marks a failure"),
        ("<td>&#10007; finding</td>", "marks a failure"),  # reviewer B, slice 14 round 1: an entity is still a mark
        ("<td>&check; finding</td>", "marks a failure"),
        ("<p>Why the justified&#32;conclusion is what it is</p>", "explains its expected output"),
        ('<section data-section="justified-conclusion"><h2>Why</h2></section>', "explains its expected output"),
        ("<p>Why the justified conclusion is what it is</p>", "explains its expected output"),
        (f"<p>{CONCLUSION}</p>", "explains its expected output"),
    ],
)
def test_a_held_page_carrying_a_verdict_marking_or_explanation_fails_the_gate(
    tmp_path: Path, added: str, problem: str
) -> None:
    from casebook.publish.gates import held_page_problems

    site = a_held_site(tmp_path, CLEAN.replace("</main>", added + "</main>"))
    found = held_page_problems(site, {"T-TAX-01": CONCLUSION})
    assert found == [f"tasks/T-TAX-01.html: a held task's page {problem}"]


@pytest.mark.parametrize(
    "record", [{"grade": {"passed": True, "score": 100}}, {"grade": None, "regraded": {"grade_before": {"score": 0}}}]
)
def test_a_held_task_s_run_record_with_a_grade_fails_the_gate(tmp_path: Path, record: dict[str, Any]) -> None:
    from casebook.publish.gates import held_page_problems

    site = a_held_site(tmp_path, CLEAN, record)
    assert held_page_problems(site, {"T-TAX-01": CONCLUSION}) == [
        "data/runs/T-TAX-01/T-TAX-01-basic-x.json: a held task's run record carries its grade"
    ]


def test_the_site_build_runs_the_gate_on_every_held_task_s_page(
    book: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A template that let a verdict through would fail the build, not publish it."""
    import casebook.publish.site_build as site_build

    task = find_task(TASKS, "T-TAX-01")
    runs = runs_with(tmp_path, published_record(task, a_graded_record("T-TAX-01")))
    render = site_build.render_site

    def leaky(*args: Any, **kwargs: Any) -> dict[str, str]:
        pages = render(*args, **kwargs)
        page = pages["tasks/T-TAX-01.html"]
        pages["tasks/T-TAX-01.html"] = page.replace("</main>", "<p>Passed: 100 of 100</p></main>")
        return pages

    monkeypatch.setattr(site_build, "render_site", leaky)
    with pytest.raises(SiteBuildError, match=r"T-TAX-01\.html: a held task's page shows a verdict"):
        build_site(book, tmp_path / "site", README, runs, TASKS, None)


def test_a_graded_record_naming_a_held_task_is_gated_wherever_it_is_filed(tmp_path: Path) -> None:
    """Reviewer A, slice 14 round 1: a held task's record filed under another task's folder."""
    from casebook.publish.gates import held_page_problems

    site = tmp_path / "site"
    (site / "data" / "runs" / "T-REC-01").mkdir(parents=True)
    record = a_graded_record("T-TAX-01")
    (site / "data" / "runs" / "T-REC-01" / "misfiled.json").write_text(json.dumps(record))
    assert held_page_problems(site, {"T-TAX-01": CONCLUSION}) == [
        "data/runs/T-REC-01/misfiled.json: a held task's run record carries its grade"
    ]


@pytest.mark.parametrize("field", ["task_id", "run_id"])
def test_a_run_record_filed_under_another_task_or_name_fails_the_site_build(
    book: Path, tmp_path: Path, field: str
) -> None:
    """Reviewer A, slice 14 round 1: the page would show it under the task it names, published under another."""
    record = a_graded_record("T-REC-05")
    runs = runs_with(tmp_path, record)
    path = runs / "T-REC-05" / f"{record['run_id']}.json"
    other = {"task_id": "T-TAX-01", "run_id": "T-REC-05-skill-20261116T135933Z-0000"}[field]
    path.write_text(json.dumps(record | {field: other}))
    with pytest.raises(SiteBuildError, match="not the folder and file it is filed under"):
        build_site(book, tmp_path / "site", README, runs, TASKS, None)
