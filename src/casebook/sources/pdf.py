"""The page every document PDF shares: US letter, the synthetic-data notice in the footer, and
fixed metadata so the same book builds the same bytes."""

import io

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Flowable, SimpleDocTemplate

from casebook.notice import NOTICE

MARGIN = 54
FOOTER_SIZE = 6.5


def _footer(canvas: Canvas, _doc: object) -> None:
    width = LETTER[0] - 2 * MARGIN
    lines = simpleSplit(NOTICE, "Helvetica", FOOTER_SIZE, width)
    canvas.saveState()
    canvas.setFont("Helvetica", FOOTER_SIZE)
    y = MARGIN - 18
    for line in reversed(lines):
        canvas.drawString(MARGIN, y, line)
        y += FOOTER_SIZE + 1.5
    canvas.restoreState()


def render(title: str, story: list[Flowable]) -> bytes:
    """The story drawn on letter pages, the notice in every page's footer."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN + 40,
        title=title,
        author="The Indus Casebook (synthetic)",
        invariant=1,
    )
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
