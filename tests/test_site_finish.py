"""Slice 14: the finished site, built from the published runs. Its pages, links and errata log; the held task pages;
a tax or RMD household's conclusion; and a walk of each kind of page at phone and desktop widths."""

import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from playwright.sync_api import Browser

from casebook.notice import NOTICE
from casebook.publish.gates import held_page_problems
from casebook.publish.site_build import SiteBuildError, build_site
from casebook.site.errata import ErrataError, load_errata
from casebook.site.tasks import is_held
from casebook.tasks.task import load_task

from .conftest import FEATURED, README, ROOT
from .test_site_browser import visible_notice, visit

TASKS = ROOT / "tasks" / "public"
RUNS = ROOT / "published" / "runs"
ERRATA = ROOT / "published" / "errata.json"
PUBLIC_TASKS = 24
WIDTHS = (390, 1440)
# One of each kind of page: the home page, a tax or RMD household, a graded task, a held task, the results.
WALK = ("index.html", "households/HH-5271.html", "tasks/T-REC-02.html", "tasks/T-TAX-01.html", "results.html")


@pytest.fixture(scope="module")
def published_site(book: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("published-site") / "site"
    build_site(book, out, README, RUNS, TASKS, None, errata=ERRATA)
    return out


def pages(site: Path) -> list[Path]:
    return sorted(site.rglob("*.html"))


def test_the_site_lists_the_20_featured_households_24_tasks_the_results_and_the_errata_log(
    published_site: Path,
) -> None:
    assert len(FEATURED) == 20
    households = sorted(p.stem for p in (published_site / "households").glob("*.html"))
    tasks = sorted(p.stem for p in (published_site / "tasks").glob("*.html"))
    assert households == list(FEATURED)
    assert tasks == sorted(p.stem for p in TASKS.glob("*.toml")) and len(tasks) == PUBLIC_TASKS
    index = (published_site / "index.html").read_text()
    assert sorted(set(re.findall(r'href="households/(HH-\d{4})\.html"', index))) == households
    assert sorted(set(re.findall(r'href="tasks/(T-[A-Z]{3}-\d{2})\.html"', index))) == tasks
    assert 'href="results.html"' in index and 'href="errata.html"' in index


def test_the_site_loads_with_no_account_or_install(published_site: Path) -> None:
    """No script, nothing fetched from elsewhere, and every link a file of the site: it works from `file://`."""
    for page in pages(published_site):
        html = page.read_text()
        assert "<script" not in html, page.name
        for link in re.findall(r'(?:href|src)="([^"]+)"', html):
            if link.startswith("data:"):
                continue
            assert not urlsplit(link).scheme and not link.startswith("//"), f"{page.name}: {link}"
            target = (page.parent / unquote(urlsplit(link).path)).resolve()
            assert target.is_file(), f"{page.relative_to(published_site)}: {link} leads nowhere"


def test_the_errata_log_has_its_page_saying_there_is_no_correction_yet(published_site: Path) -> None:
    assert load_errata(ERRATA) == []
    html = (published_site / "errata.html").read_text()
    assert 'data-correction="none"' in html and "No corrections yet" in html


def test_the_errata_log_lists_each_correction_with_its_version(book: Path, tmp_path: Path) -> None:
    errata = tmp_path / "errata.json"
    entries = [
        {"version": "0.0.2", "date": "2026-12-01", "correction": "HH-4821's fee schedule.", "ids": ["HH-4821"]},
        {"version": "0.0.3", "date": "2027-01-10", "correction": "T-REC-01's key.", "ids": ["T-REC-01"]},
    ]
    errata.write_text(json.dumps({"entries": entries}))
    build_site(book, tmp_path / "site", README, errata=errata)
    html = (tmp_path / "site" / "errata.html").read_text()
    assert re.findall(r'data-correction="([^"]+)"', html) == ["0.0.3", "0.0.2"]  # newest first
    assert "HH-4821&#39;s fee schedule." in html and "2027-01-10" in html


@pytest.mark.parametrize(
    "log",
    [
        "[]",
        '{"entries": [{"version": "0.0.2", "date": "2026-12-01", "correction": "x"}]}',
        '{"entries": [{"version": " ", "date": "2026-12-01", "correction": "x", "ids": []}]}',
        '{"entries": [{"version": "0.0.2", "date": "1 December", "correction": "x", "ids": []}]}',
        '{"entries": [{"version": "0.0.2", "date": "2026-12-01", "correction": "", "ids": []}]}',
        '{"entries": [{"version": "0.0.2", "date": "2026-12-01", "correction": "x", "ids": "HH-4821"}]}',
        "not json",
    ],
)
def test_a_malformed_errata_log_fails_the_site_build(book: Path, tmp_path: Path, log: str) -> None:
    errata = tmp_path / "errata.json"
    errata.write_text(log)
    with pytest.raises(ErrataError):
        load_errata(errata)
    with pytest.raises(SiteBuildError, match="errata log"):
        build_site(book, tmp_path / "site", README, errata=errata)


def held_tasks() -> dict[str, str]:
    tasks = [load_task(p) for p in sorted(TASKS.glob("*.toml"))]
    return {t.task_id: t.justified_conclusion for t in tasks if is_held(t)}


def test_every_held_task_page_shows_its_sources_and_outputs_and_nothing_else(published_site: Path) -> None:
    held = held_tasks()
    assert "T-TAX-01" in held and "T-REC-01" not in held
    assert held_page_problems(published_site, held) == []
    for task_id in held:
        html = (published_site / "tasks" / f"{task_id}.html").read_text()
        assert 'data-section="sources"' in html and '<pre class="output">' in html, task_id
        assert "data-regraded" not in html, task_id


def test_a_graded_task_page_still_shows_its_verdict_marking_and_explanation(published_site: Path) -> None:
    html = (published_site / "tasks" / "T-REC-02.html").read_text()
    assert 'data-outcome="passed"' in html or 'data-outcome="failed"' in html
    assert "data-criterion" in html and 'data-section="justified-conclusion"' in html
    assert 'data-section="sources"' in html


def test_a_book_level_task_names_the_whole_book_and_a_workflow_by_its_name(published_site: Path) -> None:
    html = (published_site / "tasks" / "T-TAX-05.html").read_text()
    assert "<h1>T-TAX-05: Tax-lot and RMD review</h1>" in html
    assert "Across the whole public book" in html and "households/book.html" not in html


def test_the_events_layer_names_each_security_by_its_invented_name(published_site: Path) -> None:
    for household in FEATURED:
        html = (published_site / "households" / f"{household}.html").read_text()
        events = html.split('data-truth-layer="events"')[1].split("</table>")[0]
        assert not re.search(r"\bSEC-\d{4}\b", events), household
    events = (published_site / "households" / "HH-3058.html").read_text().split('data-truth-layer="events"')[1]
    assert "Bramwell Devices Group" in events.split("</table>")[0]


def test_a_tax_or_rmd_household_page_shows_the_justified_conclusion_with_its_figures(
    published_site: Path, browser: Browser
) -> None:
    """HH-5271, T-TAX-01's household: its RMD item's conclusion and figures, as for any other item, while the task's
    page shows no verdict (docs/PLAN.md, U4)."""
    page, noise = visit(browser, (published_site / "households" / "HH-5271.html").as_uri())
    conclusion = page.locator("[data-truth-layer=conclusion]")
    assert "so its 2025 RMD of $12,729.96 was missed" in conclusion.inner_text()
    figures = dict(
        zip(
            conclusion.locator("dl.figures dt").all_inner_texts(),
            conclusion.locator("dl.figures dd").all_inner_texts(),
            strict=True,
        )
    )
    assert figures["2025 RMD, IRAs together"] == "$31,472.54"
    assert figures["401(k) RMD missed"] == "$12,729.96"
    page.close()
    assert noise == []


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("name", WALK)
def test_each_kind_of_page_at_phone_and_desktop_widths_with_a_clean_console(
    published_site: Path, browser: Browser, name: str, width: int
) -> None:
    page, noise = visit(browser, (published_site / name).as_uri(), width)
    assert visible_notice(page) == NOTICE
    assert page.locator("[data-notice]").is_visible()
    assert page.evaluate("document.documentElement.scrollWidth") <= width, "the page scrolls sideways"
    assert page.locator("main h1").first.is_visible()
    page.close()
    assert noise == []
