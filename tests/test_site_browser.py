"""Playwright on the built site: the household page shows what the spec says, with a clean console."""

import functools
import threading
from collections.abc import Iterator
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Page

from casebook.notice import NOTICE

SOURCE_SETS = ["custodian", "portfolio", "crm", "documents"]
TRUTH_LAYERS = ["events", "observations", "conclusion"]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture(scope="module")
def server(site: Path) -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(site)))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def visit(browser: Browser, url: str, width: int = 1440) -> tuple[Page, list[str]]:
    page = browser.new_page(viewport={"width": width, "height": 900})
    noise: list[str] = []
    page.on("console", lambda m: noise.append(f"console {m.type}: {m.text}"))
    page.on("pageerror", lambda e: noise.append(f"page error: {e}"))
    page.on("response", lambda r: noise.append(f"HTTP {r.status} {r.url}") if r.status >= 400 else None)
    page.goto(url)
    return page, noise


def visible_notice(page: Page) -> str:
    return " ".join(page.locator("[data-notice]").inner_text().split())


def test_the_trap_page_shows_sources_side_by_side_the_planted_item_and_three_layers(
    browser: Browser, server: str
) -> None:
    page, noise = visit(browser, f"{server}/index.html")
    page.get_by_role("link", name="HH-4821 · Okafor-Lind household").click()
    page.wait_for_url("**/households/HH-4821.html")

    assert visible_notice(page) == NOTICE
    cards = page.locator("[data-source-set]")
    assert [cards.nth(i).get_attribute("data-source-set") for i in range(cards.count())] == SOURCE_SETS
    tops = [cards.nth(i).bounding_box()["y"] for i in range(cards.count())]  # type: ignore[index]
    assert max(tops) - min(tops) < 1, f"source sets are not side by side: {tops}"
    for i in range(cards.count()):
        assert cards.nth(i).is_visible()

    planted = page.locator("[data-section=planted-item]")
    assert "PI-0001: Missed fee breakpoint" in planted.inner_text()
    layers = page.locator("[data-truth-layer]")
    assert [layers.nth(i).get_attribute("data-truth-layer") for i in range(layers.count())] == TRUTH_LAYERS
    assert "The household was overbilled by $" in layers.nth(2).inner_text()
    page.close()
    assert noise == []


def test_the_twin_page_shows_no_planted_item_and_explains_the_near_miss(browser: Browser, server: str) -> None:
    page, noise = visit(browser, f"{server}/households/HH-7350.html")
    assert visible_notice(page) == NOTICE
    assert page.locator("[data-source-set]").count() == 4
    assert (
        "None. This household is the twin in pair 1, a near miss."
        in page.locator("[data-section=planted-item]").inner_text()
    )
    assert "A near miss." in page.locator("[data-truth-layer=conclusion]").inner_text()
    page.close()
    assert noise == []


def test_every_link_on_the_trap_page_resolves(browser: Browser, server: str) -> None:
    page, noise = visit(browser, f"{server}/households/HH-4821.html")
    hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
    for href in sorted(set(hrefs)):
        response = page.request.get(href)
        assert response.ok, href
    page.close()
    assert noise == []
