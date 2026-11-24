"""Slice 17: a tax review releases the held items in its scope (docs/PLAN.md, slice 17; docs/SPEC.md, After review and
the texts under the notice). Built and tested with the fixture statement (tests/fixtures/review/): T-TAX-01 and
HH-5271's return, reviewed by "Pat Example, EA" on 1 March 2027."""

import copy
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from casebook.build import BuildError, build_book
from casebook.notice import NOTICE, UNREVIEWED_SENTENCE, contains_notice
from casebook.publish.gates import notice_problems, return_problems, run_gates
from casebook.publish.site_build import SiteBuildError, build_site
from casebook.published_text import html_visible_text, pdf_pages_text
from casebook.review_statement import (
    REVIEW_STATEMENT,
    ReviewStatementError,
    is_held,
    notice_for_task,
    parse_review_statement,
    statement_of,
)
from casebook.runner.session import HELD_KEYS, keys_root_for, published_record
from casebook.tasks.task import load_task
from casebook.watermark import UNREVIEWED, Marks, stamped_problems

from .conftest import README, ROOT, SCRIPTS, SEED
from .conftest import REVIEW_STATEMENT as FIXTURE

TASKS = ROOT / "tasks" / "public"
RUNS = ROOT / "published" / "runs"
KEYS = ROOT / "published" / "keys"
STATEMENT: dict[str, Any] = json.loads(FIXTURE.read_text())

# docs/SPEC.md, under the notice, with the fixture statement's date, reviewer and scope filled in by hand.
REVIEW_SENTENCE = (
    "Tax reviewed on 2027-03-01 by Pat Example, EA, for the RMD review of HH-5271 and its 2025 return. Answer keys "
    "and workflow judgments outside that scope have not been independently reviewed by qualified practitioners."
)
REVIEWED_NOTICE = (
    "UNVALIDATED SYNTHETIC RESEARCH PREVIEW. Household data, prices, transactions and document contents are "
    "invented. Securities appear under invented names by default; an optional mode uses real ticker identifiers with "
    "invented prices. " + REVIEW_SENTENCE + " This is not tax, investment or compliance advice and is unsuitable for "
    "filing, trading or client decisions. No performance claims are established."
)
REVIEWED_WATERMARK = "TAX REVIEWED 2027-03-01 · SYNTHETIC · NOT FOR FILING"
REVIEWED = Marks(REVIEWED_WATERMARK, REVIEWED_NOTICE)
IN_SCOPE, OUT_OF_SCOPE = "HH-5271", "HH-4821"
REVIEWED_TASK, HELD_TASK = "T-TAX-01", "T-TAX-02"


def _without(path: str) -> dict[str, Any]:
    """The fixture statement with one field, `scope.tasks` say, taken out."""
    statement = copy.deepcopy(STATEMENT)
    *parents, last = path.split(".")
    target = statement
    for part in parents:
        target = target[part]
    del target[last]
    return statement


def _with(path: str, value: Any) -> dict[str, Any]:
    statement = copy.deepcopy(STATEMENT)
    *parents, last = path.split(".")
    target = statement
    for part in parents:
        target = target[part]
    target[last] = value
    return statement


def _returns(book: Path, household: str) -> list[Path]:
    return sorted((book / "sealed" / household / "returns").rglob("*.pdf"))


# Criterion 3: a statement missing its date, reviewer or scope is rejected.


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        (_without("date"), "names no date"),
        (_without("reviewer"), "names no reviewer"),
        (_without("scope"), "names no scope"),
        (_with("date", ""), "names no date"),
        (_with("reviewer", "  "), "names no reviewer"),
        (_with("scope", {}), "names no scope"),
        (_with("date", "1 March 2027"), "is not YYYY-MM-DD"),
        (_with("scope", {"summary": "nothing", "tasks": [], "households": []}), "names no task and no household"),
        (_without("scope.summary"), "scope has exactly summary, tasks, households"),
        (_with("scope.summary", ""), "names no scope in words"),
        (_with("scope.tasks", ["TAX-01"]), "lists its tasks as a list of IDs"),
        (_with("scope.households", "HH-5271"), "lists its households as a list of IDs"),
        (_with("signed", True), "has exactly date, reviewer, scope"),
        ([], "is a JSON object"),
    ],
)
def test_a_statement_missing_its_date_reviewer_or_scope_is_rejected(statement: Any, message: str) -> None:
    with pytest.raises(ReviewStatementError, match=message):
        parse_review_statement(statement)


def test_the_fixture_statement_reads_as_its_fields() -> None:
    statement = parse_review_statement(STATEMENT)
    assert (statement.date.isoformat(), statement.reviewer) == ("2027-03-01", "Pat Example, EA")
    assert (statement.tasks, statement.households) == (frozenset({REVIEWED_TASK}), frozenset({IN_SCOPE}))


def test_the_build_refuses_a_statement_missing_its_reviewer(tmp_path: Path) -> None:
    bad = tmp_path / REVIEW_STATEMENT
    bad.write_text(json.dumps(_without("reviewer")))
    with pytest.raises(BuildError, match="names no reviewer"):
        build_book(SEED, tmp_path / "book", SCRIPTS, review_statement=bad)
    assert not (tmp_path / "book").exists()


# Criterion 1: the review sentence on tax items in scope; the reviewed watermark on returns in scope.


def test_the_reviewed_texts_are_the_spec_s() -> None:
    statement = parse_review_statement(STATEMENT)
    assert statement.sentence == REVIEW_SENTENCE
    assert statement.notice == REVIEWED_NOTICE
    assert statement.watermark == REVIEWED_WATERMARK
    # Every sentence of the notice but the one on unreviewed work stays, word for word.
    assert UNREVIEWED_SENTENCE not in statement.notice
    assert NOTICE.replace(UNREVIEWED_SENTENCE, "") == statement.notice.replace(REVIEW_SENTENCE, "")


def test_the_book_carries_the_statement_it_was_built_under(reviewed_book: Path, book: Path) -> None:
    assert statement_of(reviewed_book) == parse_review_statement(STATEMENT)
    assert statement_of(book) is None
    assert REVIEW_STATEMENT in json.loads((reviewed_book / "manifest.json").read_text())["files"]


def test_every_page_of_a_return_in_scope_carries_the_reviewed_watermark_and_notice(reviewed_book: Path) -> None:
    pdfs = _returns(reviewed_book, IN_SCOPE)
    assert pdfs
    for pdf in pdfs:
        data = pdf.read_bytes()
        assert stamped_problems(pdf.name, data, REVIEWED) == [], pdf
        for text in pdf_pages_text(data):
            assert "UNREVIEWED" not in text and REVIEWED_WATERMARK in text, pdf
            assert contains_notice(text, REVIEWED_NOTICE) and not contains_notice(text), pdf


def test_every_other_return_keeps_unreviewed_and_is_unchanged(reviewed_book: Path, book: Path) -> None:
    others = [h.name for h in (book / "sealed").iterdir() if h.name != IN_SCOPE and _returns(book, h.name)]
    assert OUT_OF_SCOPE in others
    for household in others:
        for pdf in _returns(reviewed_book, household):
            data = pdf.read_bytes()
            assert stamped_problems(pdf.name, data, UNREVIEWED) == [], pdf
            assert data == (book / pdf.relative_to(reviewed_book)).read_bytes(), pdf
    # The in-scope household's return is what changed.
    for pdf in _returns(reviewed_book, IN_SCOPE):
        assert stamped_problems(pdf.name, pdf.read_bytes(), UNREVIEWED) != [], pdf


def test_the_build_refuses_a_statement_naming_a_household_it_fills_no_return_for(tmp_path: Path) -> None:
    background = tmp_path / REVIEW_STATEMENT
    background.write_text(json.dumps(_with("scope.households", ["HH-0120"])))
    with pytest.raises(BuildError, match=r"fills no return for: \['HH-0120'\]"):
        build_book(SEED, tmp_path / "book", SCRIPTS, review_statement=background)


def _graded(record: dict[str, Any]) -> dict[str, Any]:
    """A held run as `casebook regrade` publishes it once a review statement releases its task: with its grade, which
    the private run folder kept (a stand-in grade here; the tests have no private folder)."""
    if record["state"] == "failed":
        return record
    # A grade in the shape the graders write it, taken from an open task's published run.
    grade = json.loads(next((RUNS / "T-REC-01").glob("*.json")).read_text())["grade"]
    released = {k: v for k, v in record.items() if k != "verdict_held"} | {"grade": grade}
    if record.get("regraded"):
        released["regraded"] = {**record["regraded"], "grade_before": None}
    return released


@pytest.fixture(scope="module")
def reviewed_site(reviewed_book: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The site of the reviewed book, its reviewed task's runs published again with their grades."""
    runs = tmp_path_factory.mktemp("reviewed-runs") / "runs"
    shutil.copytree(RUNS, runs)
    for path in (runs / REVIEWED_TASK).glob("*.json"):
        path.write_text(json.dumps(_graded(json.loads(path.read_text())), indent=2, sort_keys=True) + "\n")
    out = tmp_path_factory.mktemp("reviewed-site") / "site"
    build_site(reviewed_book, out, README, runs, TASKS, KEYS)
    return out


def test_a_released_task_s_runs_still_published_held_stop_the_site(reviewed_book: Path, tmp_path: Path) -> None:
    with pytest.raises(SiteBuildError, match="published again with its grade by `casebook regrade`"):
        build_site(reviewed_book, tmp_path / "site", README, RUNS, TASKS, KEYS)


def _shown(page: Path) -> str:
    return html_visible_text(page.read_text(encoding="utf-8"))


def test_the_page_of_a_task_in_scope_carries_the_review_sentence_and_every_other_page_the_notice(
    reviewed_site: Path,
) -> None:
    reviewed = _shown(reviewed_site / "tasks" / f"{REVIEWED_TASK}.html")
    assert contains_notice(reviewed, REVIEWED_NOTICE) and not contains_notice(reviewed)
    others = [p for p in reviewed_site.rglob("*.html") if p.name != f"{REVIEWED_TASK}.html"]
    assert len(others) > 40
    for page in others:
        assert contains_notice(_shown(page)) and REVIEW_SENTENCE not in " ".join(_shown(page).split()), page


def test_a_task_in_scope_is_no_longer_held_and_one_outside_it_still_is(reviewed_site: Path) -> None:
    statement = parse_review_statement(STATEMENT)
    assert not is_held(load_task(TASKS / f"{REVIEWED_TASK}.toml"), statement)
    assert is_held(load_task(TASKS / f"{HELD_TASK}.toml"), statement)
    # A task that is no tax item, named in a scope, keeps the notice: the review sentence is for tax items.
    open_task = load_task(TASKS / "T-REC-01.toml")
    assert notice_for_task(open_task, parse_review_statement(_with("scope.tasks", ["T-REC-01"]))) == NOTICE
    reviewed = (reviewed_site / "tasks" / f"{REVIEWED_TASK}.html").read_text()
    held = (reviewed_site / "tasks" / f"{HELD_TASK}.html").read_text()
    assert 'data-outcome="held"' not in reviewed
    assert 'data-outcome="held"' in held


def test_the_site_s_gates_hold_each_return_and_page_to_its_own_notice_and_watermark(
    reviewed_site: Path, reviewed_book: Path, book: Path, tmp_path: Path
) -> None:
    statement = statement_of(reviewed_book)
    metadata = next(reviewed_site.glob("data/*/metadata.json"))
    notices = {f"tasks/{REVIEWED_TASK}.html": REVIEWED_NOTICE}
    assert run_gates(reviewed_site, README, metadata, None, statement, notices) == []
    copy_ = tmp_path / "site"
    shutil.copytree(reviewed_site, copy_)
    # A return in scope still stamped "unreviewed", and one outside it stamped as reviewed, each fail.
    # The book's own folder under data/, named by its metadata: data/ also holds runs/, which a Linux runner lists
    # first (Check run 45405673580, 24 November 2026).
    data = copy_ / metadata.parent.relative_to(reviewed_site)
    inside = _returns(data, IN_SCOPE)[0]
    shutil.copyfile(book / inside.relative_to(data), inside)
    outside = _returns(data, OUT_OF_SCOPE)[0]
    stamped = _returns(reviewed_book, IN_SCOPE)[0]
    shutil.copyfile(stamped, outside)
    problems = return_problems(copy_, statement)
    assert any(p.startswith(inside.relative_to(copy_).as_posix()) and "TAX REVIEWED" in p for p in problems)
    assert any(p.startswith(outside.relative_to(copy_).as_posix()) and "'UNREVIEWED'" in p for p in problems)
    # The page of a task in scope with the plain notice, and another page with the reviewed one, each fail.
    page = copy_ / "tasks" / f"{REVIEWED_TASK}.html"
    page.write_text(page.read_text().replace(REVIEW_SENTENCE.split(". Answer")[0], UNREVIEWED_SENTENCE[:-1]))
    other = copy_ / "tasks" / f"{HELD_TASK}.html"
    other.write_text(other.read_text().replace(UNREVIEWED_SENTENCE[:-1], REVIEW_SENTENCE.split(". Answer")[0]))
    assert notice_problems(copy_, README, metadata, notices) == [
        f"tasks/{REVIEWED_TASK}.html lacks the reviewed notice",
        f"tasks/{HELD_TASK}.html lacks the notice",
    ]


def test_the_household_page_says_which_watermark_its_return_carries(reviewed_site: Path) -> None:
    inside = (reviewed_site / "households" / f"{IN_SCOPE}.html").read_text()
    outside = (reviewed_site / "households" / f"{OUT_OF_SCOPE}.html").read_text()
    assert 'data-return="reviewed"' in inside and REVIEWED_WATERMARK in inside
    assert 'data-return="unreviewed"' in outside and REVIEWED_WATERMARK not in outside


def test_the_runner_publishes_a_released_task_s_key_and_grade_and_holds_the_rest(tmp_path: Path) -> None:
    """Where `casebook run` and `casebook regrade` put a key, and what a published record keeps: a released tax
    task's key goes to the published keys and its grade is published; a held one's stays in out/keys/, its grade
    stripped."""
    statement = parse_review_statement(STATEMENT)
    released, held = load_task(TASKS / f"{REVIEWED_TASK}.toml"), load_task(TASKS / f"{HELD_TASK}.toml")
    published = tmp_path / "published" / "keys"
    assert keys_root_for(released, published, statement) == published
    assert keys_root_for(released, published, None) == HELD_KEYS
    assert keys_root_for(held, published, statement) == HELD_KEYS
    record = {"task_id": REVIEWED_TASK, "state": "mapped", "grade": {"score": 100, "passed": True}}
    assert published_record(released, record, statement) == record
    assert published_record(released, record, None)["grade"] is None
    assert published_record(held, {**record, "task_id": HELD_TASK}, statement)["grade"] is None
