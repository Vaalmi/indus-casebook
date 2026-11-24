"""The watermark and the notice on every page of a filled return, and the check that each page carries both,
visibly: "unreviewed" and the notice, or, on a return a review statement covers, the reviewed watermark and the
reviewed notice (`casebook.review_statement`).

It lives outside `tax`: drawing them is page geometry in reportlab's floats, not money, and the check
reads a page's drawing operators, whose numbers pypdf gives as floats.
"""

import dataclasses
import io
import logging
import math
from dataclasses import dataclass
from functools import cache

from pypdf import PageObject, PdfReader, PdfWriter
from pypdf.generic import ContentStream
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from casebook.notice import NOTICE, contains_notice
from casebook.published_text import pdf_pages_text

WATERMARK = "UNREVIEWED"
WATERMARK_FONT, WATERMARK_SIZE, WATERMARK_GREY = "Helvetica-Bold", 96, HexColor(0x9E9E9E)
# A longer watermark, the reviewed one, is drawn smaller, to fit this share of the page's diagonal.
WATERMARK_SPAN = 0.9
# The notice runs across the top margin, above the forms' highest text (the 1040's "1040" reaches
# 772 points up a 792-point page); tests/test_tax_forms.py checks it overlaps no form text.
NOTICE_FONT, NOTICE_SIZE, NOTICE_LEADING, NOTICE_TOP, NOTICE_SIDE = "Helvetica", 5, 6, 6, 18

logging.getLogger("pypdf").setLevel(logging.ERROR)


@dataclass(frozen=True)
class Marks:
    """What every page of a return carries: its watermark, and its notice."""

    watermark: str
    notice: str


UNREVIEWED = Marks(WATERMARK, NOTICE)


@cache
def _overlay(width: int, height: int, marks: Marks) -> PageObject:
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=(width, height), invariant=1)
    canvas.saveState()
    canvas.translate(width / 2, height / 2)
    canvas.rotate(math.degrees(math.atan2(height, width)))
    canvas.setStrokeColor(WATERMARK_GREY)
    text = canvas.beginText()
    text.setTextRenderMode(1)  # outlined, so the form's own print shows through the letters
    size = min(
        WATERMARK_SIZE, WATERMARK_SPAN * math.hypot(width, height) / stringWidth(marks.watermark, WATERMARK_FONT, 1)
    )
    text.setFont(WATERMARK_FONT, size)
    text.setTextOrigin(-stringWidth(marks.watermark, WATERMARK_FONT, size) / 2, -size / 3)
    text.textOut(marks.watermark)
    canvas.drawText(text)
    canvas.restoreState()
    canvas.setFont(NOTICE_FONT, NOTICE_SIZE)
    for row, line in enumerate(simpleSplit(marks.notice, NOTICE_FONT, NOTICE_SIZE, width - 2 * NOTICE_SIDE)):
        canvas.drawString(NOTICE_SIDE, height - NOTICE_TOP - row * NOTICE_LEADING, line)
    canvas.showPage()
    canvas.save()
    return PdfReader(io.BytesIO(buffer.getvalue())).pages[0]


def stamp_pages(writer: PdfWriter, marks: Marks = UNREVIEWED) -> None:
    """The watermark across every page of a document being written, and the notice in each page's top margin."""
    for page in writer.pages:
        page.merge_page(_overlay(int(page.mediabox.width), int(page.mediabox.height), marks))


def stamp(pdf: bytes, marks: Marks = UNREVIEWED) -> bytes:
    """The PDF with the watermark across every page and the notice in each page's top margin."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    stamp_pages(writer, marks)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# Text render modes that paint (PDF 32000-1, 9.3.6): 3 is invisible and 7 only adds to the clipping path.
FILLS, STROKES = frozenset({0, 2, 4, 6}), frozenset({1, 2, 5, 6})
WHITE = {1: (1,), 3: (1, 1, 1), 4: (0, 0, 0, 0)}  # gray, RGB, CMYK, by component count
WATERMARK_SMALLEST, NOTICE_SMALLEST = 24, 4  # points, as drawn


@dataclass
class _State:
    """The parts of the graphics state that decide whether text shows."""

    matrix: tuple[float, float, float, float] = (1, 0, 0, 1)  # the CTM's linear part
    fill: tuple[float, ...] = (0,)
    stroke: tuple[float, ...] = (0,)
    fill_alpha: float = 1
    stroke_alpha: float = 1
    mode: int = 0
    size: float = 0


def _times(
    m: tuple[float, float, float, float], n: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    return (m[0] * n[0] + m[1] * n[2], m[0] * n[1] + m[1] * n[3], m[2] * n[0] + m[3] * n[2], m[2] * n[1] + m[3] * n[3])


def _shown(text: object) -> str:
    return text.decode("latin-1") if isinstance(text, bytes) else str(text)


def _visible_text(page: PageObject, stream: ContentStream) -> str:
    """The text a content stream draws so that it shows: in a painting render mode, in a colour other than
    white, not fully transparent. Each piece is kept with its drawn size, so a caller can ask for a minimum."""
    pieces: list[str] = []
    stack: list[_State] = []
    state, text_matrix = _State(), (1.0, 0.0, 0.0, 1.0)
    states = page.get("/Resources", {}).get("/ExtGState", {})
    for operands, operator in stream.operations:
        op = operator.decode("latin-1")
        numbers = [float(o) for o in operands if isinstance(o, int | float)]
        if op == "q":
            stack.append(dataclasses.replace(state))
        elif op == "Q" and stack:
            state = stack.pop()
        elif op == "cm" and len(numbers) == 6:
            state.matrix = _times((numbers[0], numbers[1], numbers[2], numbers[3]), state.matrix)
        elif op in ("g", "rg", "k", "sc", "scn") and numbers:
            state.fill = tuple(numbers)
        elif op in ("G", "RG", "K", "SC", "SCN") and numbers:
            state.stroke = tuple(numbers)
        elif op == "gs" and operands:
            extra = states.get(operands[0], {})
            state.fill_alpha = float(extra.get("/ca", state.fill_alpha))
            state.stroke_alpha = float(extra.get("/CA", state.stroke_alpha))
        elif op == "Tr" and numbers:
            state.mode = int(numbers[0])
        elif op == "Tf" and len(numbers) == 1:
            state.size = numbers[0]
        elif op == "BT":
            text_matrix = (1.0, 0.0, 0.0, 1.0)
        elif op == "Tm" and len(numbers) == 6:
            text_matrix = (numbers[0], numbers[1], numbers[2], numbers[3])
        elif op in ("Tj", "'", '"', "TJ") and operands:
            painted = (state.mode in FILLS and state.fill != WHITE.get(len(state.fill)) and state.fill_alpha > 0) or (
                state.mode in STROKES and state.stroke != WHITE.get(len(state.stroke)) and state.stroke_alpha > 0
            )
            m = _times(text_matrix, state.matrix)
            drawn = state.size * math.sqrt(abs(m[0] * m[3] - m[1] * m[2]))
            if painted:
                last = operands[-1]
                text = (
                    "".join(_shown(t) for t in last if not isinstance(t, int | float)) if op == "TJ" else _shown(last)
                )
                pieces.append(f"{drawn:.1f}\t{text}")
    return "\n".join(pieces)


def _ascii_prefix(text: str) -> bytes:
    """The part of a mark before its first character outside ASCII, as a content stream writes it plainly."""
    return text.encode("ascii", errors="replace").split(b"?", 1)[0]


def _marks_shown(page: PageObject, marks: Marks) -> tuple[bool, bool]:
    """Whether the watermark, at its size, and the whole notice, at a readable size, are drawn visibly in
    the page's own content. Only the content streams that hold them are read: a filled form's own
    drawing is large, and the stamp is a stream of its own."""
    contents = page.get("/Contents")
    if contents is None:
        return False, False
    resolved = contents.get_object()
    streams = list(resolved) if isinstance(resolved, list) else [contents]
    watermark = notice = False
    for ref in streams:
        data = ref.get_object().get_data()
        if _ascii_prefix(marks.watermark) not in data and b"UNVALIDATED" not in data:
            continue
        drawn = _visible_text(page, ContentStream(ref.get_object(), page.pdf))
        lines = [line.split("\t", 1) for line in drawn.splitlines()]
        watermark = watermark or any(
            marks.watermark in text and float(size) >= WATERMARK_SMALLEST for size, text in lines
        )
        readable = " ".join(text for size, text in lines if float(size) >= NOTICE_SMALLEST)
        notice = notice or contains_notice(readable, marks.notice)
    return watermark, notice


def stamped_problems(name: str, pdf: bytes, marks: Marks = UNREVIEWED) -> list[str]:
    """One problem for each page that lacks the watermark or the notice `marks` gives: in its text, or drawn so that
    it shows (an invisible render mode, white, transparent or tiny ink does not count)."""
    problems: list[str] = []
    pages = PdfReader(io.BytesIO(pdf)).pages
    watermark = marks.watermark
    for number, (page, text) in enumerate(zip(pages, pdf_pages_text(pdf), strict=True), 1):
        watermark_shown, notice_shown = _marks_shown(page, marks)
        if watermark not in text:
            problems.append(f"{name}: page {number} has no {watermark!r} watermark")
        elif not watermark_shown:
            problems.append(f"{name}: page {number}'s {watermark!r} watermark is not drawn so that it shows")
        if not contains_notice(text, marks.notice):
            problems.append(f"{name}: page {number} does not carry the notice")
        elif not notice_shown:
            problems.append(f"{name}: page {number}'s notice is not drawn so that it shows")
    return problems
