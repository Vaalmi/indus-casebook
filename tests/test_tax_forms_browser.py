"""A filled form opens in a real browser PDF viewer with its values visible: Chromium's own viewer, page 1
of each form, the same form with and without one value, compared pixel by pixel."""

import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image, ImageChops
from playwright.sync_api import Browser, Page, Playwright
from pypdf import PdfReader

from casebook.tax.forms import FORMS, fill

from .test_tax_forms import form_fields, official, the_map

# One amount line on page 1 of each form, where the viewer shows it without scrolling.
LINE_ON_PAGE_ONE = {
    "f1040": "1a",
    "f1040s1": "1",
    "f1040s1a": "1",
    "f1040s2": "1a",
    "f1040s3": "1",
    "f1040sa": "1",
    "f1040sb": "part1_row1_amount",
    "f1040sd": "1b_d",
    "f8949": "part1_row1_d",
    "f8606": "1",
    "f8960": "1",
    "f8959": "1",
}
VALUE = "987,654."
WIDTH, HEIGHT = 900, 1200
SLACK = 6  # pixels: the text's ascent may reach a little beyond the field's box
PAPER = 200  # grey level: the page's paper is lighter, the viewer's background darker


@pytest.fixture(scope="module")
def viewer(playwright: Playwright) -> Iterator[Browser]:
    """Full Chromium in its new headless mode, which carries the browser's built-in PDF viewer; the
    headless shell the other browser tests use has none."""
    chromium = playwright.chromium.launch(channel="chromium")
    yield chromium
    chromium.close()


# Screenshots in a row that must match before the viewer counts as finished: under load it can pause
# between a coarse first drawing and the final one, long enough for two shots to match.
SETTLED = 3


def settled_screenshot(page: Page, path: Path) -> Image.Image:
    """A screenshot once the viewer has finished drawing: SETTLED in a row the same, 250 ms apart."""
    shots: list[bytes] = []
    for _ in range(60):
        shots = [*shots[-(SETTLED - 1) :], page.screenshot()]
        if len(shots) == SETTLED and len(set(shots)) == 1:
            shot = shots[-1]
            break
        page.wait_for_timeout(250)
    else:
        pytest.fail(f"the viewer never settled on {path.name}")
    path.write_bytes(shot)
    return Image.open(io.BytesIO(shot)).convert("RGB")


def shown(viewer: Browser, pdf: bytes, path: Path) -> Image.Image:
    path.with_suffix(".pdf").write_bytes(pdf)
    page = viewer.new_page(viewport={"width": WIDTH, "height": HEIGHT})
    # No toolbar or thumbnails, so page 1 fills the width and nothing else on screen changes.
    page.goto(f"{path.with_suffix('.pdf').as_uri()}#toolbar=0&navpanes=0")
    try:
        return settled_screenshot(page, path)
    finally:
        page.close()


def page_on_screen(image: Image.Image, page_width: int) -> tuple[int, int, float]:
    """Where the viewer drew page 1, read from the screenshot itself: its left and top edges in pixels,
    and pixels per point. The paper is light; the viewer's background is dark."""
    grey = image.convert("L")
    middle = HEIGHT // 2
    paper = [x for x in range(WIDTH) if grey.getpixel((x, middle)) > PAPER]  # type: ignore[operator]
    top = next(y for y in range(HEIGHT) if grey.getpixel((WIDTH // 2, y)) > PAPER)  # type: ignore[operator]
    return paper[0], top, (paper[-1] - paper[0] + 1) / page_width


@pytest.mark.parametrize("form", FORMS)
def test_a_filled_value_shows_in_the_browser_pdf_viewer_where_its_line_is(
    viewer: Browser, form: str, tmp_path: Path
) -> None:
    key = LINE_ON_PAGE_ONE[form]
    blank = shown(viewer, fill(form, {}, f"{form} viewer test"), tmp_path / f"{form}-blank.png")
    filled = shown(viewer, fill(form, {key: VALUE}, f"{form} viewer test"), tmp_path / f"{form}-filled.png")

    changed = ImageChops.difference(blank, filled).getbbox()
    assert changed is not None, f"{form}: {key} filled with {VALUE!r} changed nothing on screen"

    field = form_fields(form)[the_map(form)[key]]
    assert field.page == 1
    mediabox = PdfReader(official(form)).pages[0].mediabox
    page_height = int(mediabox.height)
    left_edge, top_edge, scale = page_on_screen(blank, int(mediabox.width))
    x0, y0, x1, y1 = field.rect
    box = (
        left_edge + x0 * scale - SLACK,
        top_edge + (page_height - y1) * scale - SLACK,
        left_edge + x1 * scale + SLACK,
        top_edge + (page_height - y0) * scale + SLACK,
    )
    left, top, right, bottom = changed
    assert box[0] <= left and right <= box[2] and box[1] <= top and bottom <= box[3], (
        f"{form}: the screen changed at {changed}, outside line {key}'s box {tuple(round(v) for v in box)}"
    )
