"""The task page: what each arm produced, the failure marked, the run named; the gates on run outputs."""

import json
import re
import shutil
from pathlib import Path

import pytest
from playwright.sync_api import Browser

from casebook.cli import main
from casebook.publish.site_build import SiteBuildError, build_site
from casebook.site.tasks import UnnamedResultError

from .conftest import README, ROOT, StandIn
from .test_run_session import answer_for
from .test_site_browser import visit

TASKS = ROOT / "tasks" / "public"


@pytest.fixture
def runs(tmp_path: Path, real_book: Path, standin_cli: StandIn) -> Path:
    paths = ["--keys", str(tmp_path / "keys"), "--runs", str(tmp_path / "runs"), "--tasks", str(TASKS)]

    def run(arm: str) -> None:
        main(["run", "--task", "T-REC-01", "--arm", arm, "--book", str(real_book), *paths])

    standin_cli.answer.write_text(answer_for(real_book).replace('"fee_error"', '"no_fee_error"'))
    run("basic")
    standin_cli.set("error")
    run("checklist")
    standin_cli.set("answer")
    standin_cli.answer.write_text(answer_for(real_book, "Ngozi's VTI was billed on its own."))
    run("skill")
    return tmp_path / "runs"


def build(book: Path, out: Path, runs: Path) -> int:
    return build_site(book, out, README, runs, TASKS, runs.parent / "keys")


def test_the_task_page_shows_each_arm_with_the_failure_marked_and_the_run_named(
    book: Path, runs: Path, tmp_path: Path, browser: Browser
) -> None:
    site = tmp_path / "site"
    assert build(book, site, runs) == 4
    page, noise = visit(browser, (site / "tasks" / "T-REC-01.html").as_uri())
    arms = page.locator("[data-arm]")
    assert [arms.nth(i).get_attribute("data-arm") for i in range(3)] == ["basic", "checklist", "skill"]
    basic, checklist, skill = (page.locator(f"[data-arm={a}]") for a in ("basic", "checklist", "skill"))
    assert basic.locator("[data-outcome]").get_attribute("data-outcome") == "failed"
    assert basic.locator("[data-criterion=finding]").get_attribute("class") == "miss"
    assert "Run failed, not scored: CLI error" in checklist.inner_text()
    assert skill.locator("[data-outcome]").get_attribute("data-outcome") == "passed"
    assert re.fullmatch(
        r"Claude Code 0\.0\.0 · model claude-opus-5-5 · \d{4}-\d\d-\d\d", skill.locator("[data-run-name]").inner_text()
    )
    skill.locator("summary").click()
    assert "Larkspur Total Market Fund was billed on its own." in skill.inner_text()
    assert "householding agreement AGR-4821-3" in page.locator("[data-section=justified-conclusion]").inner_text()
    page.close()
    assert noise == []


def test_a_real_ticker_in_a_published_run_output_fails_the_site_build(book: Path, runs: Path, tmp_path: Path) -> None:
    record = next(runs.glob("T-REC-01/*[0-9a-f].json"))
    data = json.loads(record.read_text())
    data["output"] = "Sell the MSFT lot"
    record.write_text(json.dumps(data))
    with pytest.raises(SiteBuildError, match=r"real ticker 'MSFT'"):
        build(book, tmp_path / "site", runs)


def test_a_result_without_its_model_cannot_be_published(book: Path, runs: Path, tmp_path: Path) -> None:
    record = next(p for p in runs.glob("T-REC-01/*[0-9a-f].json") if json.loads(p.read_text())["state"] == "mapped")
    data = json.loads(record.read_text())
    data["models_reported"] = []
    record.write_text(json.dumps(data))
    with pytest.raises(UnnamedResultError, match="lacks models_reported"):
        build(book, tmp_path / "site", runs)


def test_without_runs_the_site_has_no_task_pages(book: Path, tmp_path: Path) -> None:
    empty = tmp_path / "none"
    assert build_site(book, tmp_path / "site", README, empty, TASKS, None) == 3
    assert not (tmp_path / "site" / "tasks").exists()
    shutil.rmtree(tmp_path / "site")
