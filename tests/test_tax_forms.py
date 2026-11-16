"""The official forms: their sources, each line-to-field map checked against the form's own labels, the
fill and read-back, and the watermark and notice on every page."""

import hashlib
import io
import re
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject
from reportlab.pdfgen.canvas import Canvas

from casebook.notice import NOTICE, contains_notice
from casebook.tax.forms import FORMS, WATERMARK, FormsError, fill, keys, read_back, stamp, stamped_problems

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "casebook" / "tax" / "forms"
XFA = "{http://www.xfa.org/schema/xfa-template/3.6/}"


@dataclass(frozen=True)
class Field:
    name: str
    kind: str  # "/Tx" or "/Btn"
    page: int
    rect: tuple[int, int, int, int]
    max_length: int | None
    label: str


def official(form: str) -> Path:
    return PACKAGE / "pdfs" / f"{form}--2025.pdf"


def the_map(form: str) -> dict[str, str]:
    return tomllib.loads((PACKAGE / "maps" / f"{form}.toml").read_text())["fields"]


def xfa_labels(reader: PdfReader) -> dict[str, str]:
    """Each field's spoken label from the XFA template, by the AcroForm name the same path gives it."""
    packets: Any = reader.trailer["/Root"]["/AcroForm"]["/XFA"]  # type: ignore[index]
    template = next(
        packets[i + 1].get_object().get_data() for i in range(0, len(packets), 2) if packets[i] == "template"
    )
    labels: dict[str, str] = {}

    def named_children(node: ET.Element) -> list[ET.Element]:
        found: list[ET.Element] = []
        for child in node:
            tag = child.tag.removeprefix(XFA)
            if tag in ("subform", "field", "exclGroup") and child.get("name"):
                found.append(child)
            elif tag in ("subform", "area", "subformSet"):  # unnamed containers are not in the path
                found += named_children(child)
        return found

    def walk(node: ET.Element, path: str) -> None:
        seen: dict[str, int] = {}
        for child in named_children(node):
            name = child.get("name", "")
            index = seen.get(name, 0)
            seen[name] = index + 1
            here = f"{path}.{name}[{index}]" if path else f"{name}[{index}]"
            if child.tag == XFA + "field":
                speak = child.find(f"{XFA}assist/{XFA}speak")
                labels[here] = " ".join((speak.text or "").split()) if speak is not None else ""
            else:
                walk(child, here)

    walk(ET.fromstring(template), "")
    return labels


def form_fields(form: str) -> dict[str, Field]:
    reader = PdfReader(official(form))
    labels = xfa_labels(reader)
    fields: dict[str, Field] = {}
    for number, page in enumerate(reader.pages, 1):
        for annotation in page.get("/Annots", []):
            widget = annotation.get_object()
            parts: list[str] = []
            node: DictionaryObject | None = widget
            while node is not None:
                parts.insert(0, str(node["/T"]))
                parent = node.get("/Parent")
                node = parent.get_object() if parent is not None else None
            name = ".".join(parts)
            rect = widget["/Rect"]
            x0, y0, x1, y1 = (round(rect[i]) for i in range(4))
            length = widget.get("/MaxLen")
            fields[name] = Field(
                name, str(widget["/FT"]), number, (x0, y0, x1, y1), length and int(length), labels[name]
            )
    return fields


# --- Reading a line label the way the form prints it -------------------------------------------------------

MARKER = re.compile(r"(?<![\w(/$.,-])(\d{1,2})([a-z]{0,2})\.(?=\s|$)")
FIRST_SUBLINE = re.compile(r"\sa\.\s")  # "8. Other income: a. Net operating loss" is line 8a
COLUMN = re.compile(r"\(([a-h]|i(?: i){0,2})\) [A-Z]")
LINE_KEY = re.compile(r"(\d{1,2}[a-z]{0,2})(?:_(.+))?")


def line_of(label: str) -> str | None:
    """The line a label names: its first line number, as "1a." or as "8. ... a." for a first sub-line."""
    text = re.sub(r"^Page \d+\. ", "", label)
    found = MARKER.search(text)
    if found is None:
        return None
    number, letters = found.groups()
    if not letters and FIRST_SUBLINE.search(text[found.end() :]):
        letters = "a"
    return number + letters


def words_of(label: str) -> str:
    # The labels spell abbreviations out for screen readers ("Q C D", "S S N"); read them as printed.
    return re.sub(r"\b([A-Z]) (?=[A-Z]\b)", r"\1", label).lower()


def has_words(label: str, words: list[str]) -> bool:
    text = words_of(label)
    return all(re.search(rf"(?<![\w]){re.escape(word)}(?![\w])", text) for word in words)


def column_of(label: str) -> str | None:
    found = COLUMN.findall(label)
    return found[-1].replace(" ", "") if found else None


def right_of(fields: dict[str, Field], anchor: Field, fragment: str) -> set[str]:
    beside = [f for f in fields.values() if f.page == anchor.page and abs(f.rect[1] - anchor.rect[1]) <= 4]
    beside = [f for f in beside if f.rect[0] > anchor.rect[0] and fragment in f.label]
    return {min(beside, key=lambda f: f.rect[0]).name} if beside else set()


# Keys the line rules cannot read: headers, check boxes and fields whose label names no line, and
# lines whose label words differ from the key. Each is a fragment of the form's own label, unique on the
# form, or ("right_of", key, fragment): the nearest field to the right of that key's, on its row.
Rule = str | tuple[str, str, str]
NAMES: dict[str, Rule] = {"names": "Name(s) shown on", "ssn": "Your social security number."}
SPECIAL: dict[str, dict[str, Rule]] = {
    "f1040": {
        "name": "Your first name and middle initial.",
        "last_name": ("right_of", "name", "Last name."),
        "ssn": "Your social security number.",
        "spouse_name": "spouse's first name and middle initial.",
        "spouse_last_name": ("right_of", "spouse_name", "Last name."),
        "spouse_ssn": "Spouse's social security number.",
        "deceased": "Deceased.",
        "deceased_mm": ("right_of", "deceased", "M M."),
        "deceased_dd": ("right_of", "deceased_mm", "D D."),
        "deceased_yyyy": ("right_of", "deceased_dd", "Y Y Y Y."),
        "spouse_deceased_mm": "Spouse. M M.",
        "spouse_deceased_dd": ("right_of", "spouse_deceased_mm", "D D."),
        "spouse_deceased_yyyy": ("right_of", "spouse_deceased_dd", "Y Y Y Y."),
        "address": "Home address (number and street).",
        "apt": "Apt. no.",
        "city": "City, town, or post office.",
        "state": ("right_of", "city", "State."),
        "zip": "Z I P code.",
        "foreign_country": "Foreign country name.",
        "foreign_province": "Foreign province/state/county.",
        "foreign_postal_code": "Foreign postal code.",
        "main_home_in_us": "was in the U.S. for more than half of 2025.",
        "campaign_you": "Presidential Election Campaign.",
        "campaign_spouse": ("right_of", "campaign_you", "Spouse."),
        "status_single": "Check only one box. Single.",
        "status_mfj": "Married filing jointly (even if only one had income).",
        "status_mfs": "Married filing separately (M F S).",
        "status_hoh": "Head of household (H O H).",
        "status_qss": "Qualifying surviving spouse (Q S S).",
        "mfs_spouse_name": "S S N above and full name here",
        "hoh_qss_child_name": "enter the child's name if the qualifying person is a child",
        "nonresident_spouse": "If treating a nonresident alien or dual-status alien spouse",
        "nonresident_spouse_name": "and enter their name",
        "digital_assets_yes": "dispose of a digital asset",
        "digital_assets_no": ("right_of", "digital_assets_yes", "No."),
        "dependents_more_than_four": "If more than four dependents",
        "lived_apart": "you lived apart from your spouse for the last 6 months of 2025",
        # The form's label for this box says "27c."; the printed form puts it on line 28.
        "actc_opt_out": "If you do not want to claim the A C T C, check here.",
    },
    "f1040s1": NAMES,
    "f1040s1a": NAMES,
    "f1040s2": {
        **NAMES,
        "1y_type": "1y. Other additions to tax (see instructions):",
        "17a_type": "17. Other additional taxes: a. Recapture of other credits.",
        "8_check_here": "If not required, check here",
    },
    "f1040s3": {**NAMES, "13z_type": "13z. Other nonrefundable credits (see instructions):"},
    "f1040sa": NAMES,
    "f1040sb": {
        "names": "Name(s) shown on return.",
        "ssn": "Your social security number.",
        "7a_yes": "located in a foreign country? See instructions. Yes.",
        "7a_no": ("right_of", "7a_yes", "No."),
        "7a_fbar_yes": "to report that financial interest or signature authority?",
        "7a_fbar_no": ("right_of", "7a_fbar_yes", "No."),
        "7b_line1": "list the name(s) of the foreign country",
        "7b_line2": "7b. Line 2 of 2.",
    },
    "f1040sd": {
        **NAMES,
        "qof_yes": "qualified opportunity fund",
        "qof_no": ("right_of", "qof_yes", "No."),
    },
    "f8949": {
        "names": "Page 1. Name(s) shown on return.",
        "ssn": ("right_of", "names", "Social security number or taxpayer identification number."),
        "names_page2": "Page 2. Name(s) shown on return.",
        "ssn_page2": ("right_of", "names_page2", "Social security number or taxpayer identification number."),
    },
    "f8606": {"names": "Page 1. Name.", "ssn": "Your social security number."},
    "f8960": {"names": "Name(s) shown on your tax return.", "ssn": "Your social security number or E I N."},
    "f8959": NAMES,
}
DEPENDENT_ROWS = {
    "first_name": "(1) First name.",
    "last_name": "(2) Last name.",
    "ssn": "(3) S S N.",
    "relationship": "(4) Relationship.",
    "lived_with_you": "(a) Yes.",
    "lived_in_us": "(b) And in the U.S.",
    "student": "Full-time student.",
    "disabled": "Permanently and totally disabled.",
    "child_tax_credit": "Child tax credit.",
    "other_dependents_credit": "Credit for other dependents.",
}


def accepted(form: str, key: str, mapped: dict[str, str], fields: dict[str, Field]) -> set[str]:
    """Every field of the form whose label says it holds `key`. A map entry is right when this is exactly
    its own field: a neighbouring field, or one with the same words, never passes."""
    everything = list(fields.values())
    rule = SPECIAL[form].get(key)
    if isinstance(rule, tuple):
        _, anchor, fragment = rule
        return right_of(fields, fields[mapped[anchor]], fragment)
    if rule is not None:
        return {f.name for f in everything if rule in f.label}
    if found := re.fullmatch(r"dependent(\d)_(\w+)", key):
        column, row = f"Column: Dependent {found[1]}.", DEPENDENT_ROWS[found[2]]
        return {f.name for f in everything if column in f.label and row in f.label}
    if found := re.fullmatch(r"part([12])_row(\d+)_([a-h])", key):  # Form 8949's rows
        page, row, column = int(found[1]), found[2], found[3]
        return {
            f.name for f in everything if f.page == page and f"Row: {row}." in f.label and column_of(f.label) == column
        }
    if found := re.fullmatch(r"part([12])_total_([degh])", key):
        page, column = int(found[1]), found[2]
        return {
            f.name for f in everything if f.page == page and "2. Totals." in f.label and column_of(f.label) == column
        }
    if found := re.fullmatch(r"part([12])_box_([a-l])", key):
        page, box = int(found[1]), found[2].upper()
        return {f.name for f in everything if f.page == page and f.kind == "/Btn" and f"({box}) " in f.label}
    if found := re.fullmatch(r"part([12])_row(\d+)_(payer|amount)", key):  # Schedule B's rows
        line, rows = ("1", 14) if found[1] == "1" else ("5", 15)
        row, amount = found[2], found[3] == "amount"
        return {
            f.name
            for f in everything
            if line_of(f.label) == line and f"Line {row} of {rows}." in f.label and ("Amount." in f.label) == amount
        }
    found = LINE_KEY.fullmatch(key)
    assert found, f"{form}: {key!r} is neither a line nor a key the test knows"
    line, suffix = found[1], found[2]
    candidates = [f for f in everything if line_of(f.label) == line]
    if suffix is None:  # the line's amount: its rightmost field
        return {max(candidates, key=lambda f: f.rect[0]).name} if candidates else set()
    if re.fullmatch(r"[a-h]|i{1,3}", suffix):
        return {f.name for f in candidates if column_of(f.label) == suffix}
    words = suffix.split("_")
    siblings = [k.split("_")[1:] for k in mapped if k.startswith(f"{line}_") and LINE_KEY.fullmatch(k)]
    wider = [other for other in siblings if set(other) > set(words)]
    return {
        f.name
        for f in candidates
        if has_words(f.label, words) and not any(has_words(f.label, other) for other in wider)
    }


# --- Sources -----------------------------------------------------------------------------------------------


def test_every_official_pdf_matches_its_recorded_source_and_hash() -> None:
    sources = tomllib.loads((PACKAGE / "pdfs" / "SOURCES.toml").read_text())
    assert tuple(sources) == FORMS
    for form, source in sources.items():
        assert source["file"] == f"{form}--2025.pdf"
        assert source["url"] == f"https://www.irs.gov/pub/irs-prior/{form}--2025.pdf"
        assert str(source["retrieved"]) == "2026-11-16"
        assert hashlib.sha256((PACKAGE / "pdfs" / source["file"]).read_bytes()).hexdigest() == source["sha256"], form
    assert sorted(p.name for p in (PACKAGE / "pdfs").glob("*.pdf")) == sorted(f"{f}--2025.pdf" for f in FORMS)
    assert sorted(p.stem for p in (PACKAGE / "maps").glob("*.toml")) == sorted(FORMS)


# --- The maps ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("form", FORMS)
def test_every_mapped_field_exists_and_no_two_keys_share_one(form: str) -> None:
    mapped, fields = the_map(form), form_fields(form)
    assert set(mapped.values()) <= set(fields), sorted(set(mapped.values()) - set(fields))
    assert len(set(mapped.values())) == len(mapped)
    assert keys(form) == frozenset(mapped)


@pytest.mark.parametrize("form", FORMS)
def test_each_map_entry_is_the_one_field_the_form_labels_with_its_line(form: str) -> None:
    mapped, fields = the_map(form), form_fields(form)
    wrong = {}
    for key, name in mapped.items():
        found = accepted(form, key, mapped, fields)
        if found != {name}:
            wrong[key] = (name.rsplit(".", 1)[-1], sorted(n.rsplit(".", 1)[-1] for n in found))
    assert not wrong, wrong


def test_the_line_reader_reads_the_forms_own_labels() -> None:
    assert line_of("Income. Attach Form(s) W-2 here. Also attach Forms W-2G and 1099-R. 1a. Total amount") == "1a"
    assert line_of("8. Other income: a. Open parenthesis. Net operating loss.") == "8a"
    assert line_of("3. Add lines 1 and 2e.") == "3"
    assert line_of("Page 2. Part I I. Adjustments to Income. 11. Educator expenses.") == "11"
    assert line_of("Your social security number.") is None
    assert column_of("Row: 1. Column: (d) Proceeds (sales price) (see instructions).") == "d"
    assert column_of("2. Totals. Add the amounts in columns (d), (e), (g), and (h). (h) Gain or (loss).") == "h"


def test_a_wrong_map_entry_fails_the_label_check() -> None:
    mapped, fields = the_map("f1040"), form_fields("f1040")
    swapped = {**mapped, "1a": mapped["1b"], "1b": mapped["1a"], "4c_3": mapped["4c_3_specify"]}
    assert accepted("f1040", "1a", swapped, fields) != {swapped["1a"]}
    assert accepted("f1040", "1b", swapped, fields) != {swapped["1b"]}
    assert accepted("f1040", "4c_3", swapped, fields) != {swapped["4c_3"]}


def test_the_keys_follow_the_printed_forms() -> None:
    assert {"name", "last_name", "ssn", "spouse_name", "spouse_last_name", "spouse_ssn"} <= keys("f1040")
    assert {"status_single", "status_mfj", "status_mfs", "status_hoh", "status_qss"} <= keys("f1040")
    assert {"1a", "1z", "2a", "2b", "3a", "3b", "4a", "4b", "11a", "11b", "12e", "15", "16", "24", "25a", "37"} <= keys(
        "f1040"
    )
    assert {"names", "ssn", "1b_d", "1b_h", "8b_g", "16", "21"} <= keys("f1040sd")
    assert {f"part1_box_{b}" for b in "abcghi"} | {f"part2_box_{b}" for b in "defjkl"} <= keys("f8949")
    assert {"part1_row11_h", "part2_row1_a", "part1_total_d", "part2_total_g"} <= keys("f8949")
    assert {"part1_row14_payer", "part1_row14_amount", "part2_row15_amount", "4", "6"} <= keys("f1040sb")
    assert {str(n) for n in range(1, 10)} | {"15a", "15b", "15c", "25c"} <= keys("f8606")
    assert {"1", "2", "3", "4a", "4c", "5a", "5d", "8", "9a", "9d", "11", "12", "16", "17"} <= keys("f8960")
    assert {str(n) for n in range(1, 25)} <= keys("f8959")


# --- Filling -----------------------------------------------------------------------------------------------


def sample_values(form: str) -> dict[str, str | bool]:
    """A distinct value for every key: each text field gets its own number, cut to the field's length, and
    every other box is checked."""
    fields, values = form_fields(form), {}
    for i, (key, name) in enumerate(sorted(the_map(form).items())):
        field = fields[name]
        if field.kind == "/Btn":
            values[key] = i % 2 == 0
        else:
            text = f"{i + 1:,}.{i % 100:02d}"
            values[key] = text if field.max_length is None else str(i + 1).zfill(field.max_length)[-field.max_length :]
    return values


@pytest.mark.parametrize("form", FORMS)
def test_every_key_filled_reads_back_the_same(form: str) -> None:
    values = sample_values(form)
    pdf = fill(form, values, f"Test {form}")
    assert read_back(form, pdf) == {k: v for k, v in values.items() if v is not False}


def test_a_cleared_box_and_a_blank_line_read_back_as_absent() -> None:
    pdf = fill("f1040", {"status_mfj": True, "status_single": False, "1a": "12,345.", "1b": ""}, "Test")
    assert read_back("f1040", pdf) == {"status_mfj": True, "1a": "12,345."}


def test_a_filled_form_drops_the_xfa_layer_and_carries_the_title() -> None:
    reader = PdfReader(io.BytesIO(fill("f1040", {"1a": "1,000."}, "HH-0000 2025 Form 1040")))
    root = reader.root_object
    assert "/XFA" not in cast(DictionaryObject, root["/AcroForm"])
    assert "/Perms" not in root
    assert reader.metadata is not None and reader.metadata.title == "HH-0000 2025 Form 1040"
    assert b"/XFA" not in fill("f8949", {}, "x")


def test_the_same_inputs_give_the_same_bytes() -> None:
    values = sample_values("f1040")
    again = dict(reversed(list(values.items())))
    assert fill("f1040", values, "Same") == fill("f1040", again, "Same")


def test_the_filler_refuses_what_a_form_cannot_take() -> None:
    with pytest.raises(FormsError, match="'99z'"):
        fill("f1040", {"99z": "1."}, "x")
    with pytest.raises(FormsError, match="check box"):
        fill("f1040", {"status_mfj": "yes"}, "x")
    with pytest.raises(FormsError, match="holds text"):
        fill("f1040", {"1a": True}, "x")
    with pytest.raises(FormsError, match="at most 9 characters"):
        fill("f1040", {"ssn": "000-12-3456"}, "x")
    with pytest.raises(FormsError, match="no official form"):
        fill("f1041", {}, "x")


# --- The watermark and the notice --------------------------------------------------------------------------


@pytest.mark.parametrize("form", FORMS)
def test_every_page_carries_the_watermark_and_the_notice(form: str) -> None:
    pdf = fill(form, {}, f"Test {form}")
    pages = PdfReader(io.BytesIO(pdf)).pages
    assert len(pages) == len(PdfReader(official(form)).pages)
    for page in pages:
        text = page.extract_text()
        assert "UNREVIEWED" in text
        assert contains_notice(text)
    assert stamped_problems(form, pdf) == []


def glyph_tops(page: object) -> list[tuple[float, float, str]]:
    """Each run of text on a page: its baseline, the top of its em box, and the text."""
    runs: list[tuple[float, float, str]] = []

    def visit(text: str, cm: list[float], tm: list[float], _font: object, size: float) -> None:
        if text.strip():
            baseline = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            runs.append((baseline, baseline + size * abs(tm[3] * cm[3] + tm[2] * cm[1]), text.strip()))

    page.extract_text(visitor_text=visit)  # type: ignore[attr-defined]
    return runs


@pytest.mark.parametrize("form", FORMS)
def test_the_notice_sits_above_every_line_of_the_forms_own_text(form: str) -> None:
    stamped = PdfReader(io.BytesIO(stamp(official(form).read_bytes()))).pages
    for number, page in enumerate(PdfReader(official(form)).pages):
        highest = max(top for _, top, _ in glyph_tops(page))
        notice = [run for run in glyph_tops(stamped[number]) if run[2] in NOTICE and len(run[2]) > 40]
        assert notice, f"{form} page {number + 1}: the notice's lines were not found"
        lowest = min(baseline for baseline, _, _ in notice)
        # Helvetica's descender is under a quarter of the 5-point size.
        assert lowest - 2 > highest, f"{form} page {number + 1}: notice at {lowest}, form text up to {highest}"
        assert max(top for _, top, _ in notice) <= int(page.mediabox.height)


def overlay(width: int, height: int, *, watermark: bool, notice: bool) -> PdfReader:
    """The test's own stamp, with only one of the two marks."""
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=(width, height), invariant=1)
    if watermark:
        canvas.setFont("Helvetica-Bold", 60)
        canvas.drawString(100, 400, WATERMARK)
    if notice:
        canvas.setFont("Helvetica", 4)
        canvas.drawString(10, height - 10, NOTICE)
    canvas.save()
    return PdfReader(io.BytesIO(buffer.getvalue()))


def written(writer: PdfWriter) -> bytes:
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def with_page_two(stamped: bytes, other: bytes) -> bytes:
    """The stamped form with its second page taken from another PDF."""
    writer = PdfWriter()
    writer.add_page(PdfReader(io.BytesIO(stamped)).pages[0])
    writer.add_page(PdfReader(io.BytesIO(other)).pages[1])
    return written(writer)


def test_a_page_without_either_mark_is_named_once_for_each() -> None:
    stamped = fill("f1040", {"1a": "1,000."}, "Test")
    assert stamped_problems("HH-0000 Form 1040", stamped) == []

    problems = stamped_problems("HH-0000 Form 1040", with_page_two(stamped, official("f1040").read_bytes()))
    assert len(problems) == 2
    assert all(p.startswith("HH-0000 Form 1040: page 2 ") for p in problems)
    assert sum("watermark" in p for p in problems) == 1
    assert sum("notice" in p for p in problems) == 1


@pytest.mark.parametrize(("watermark", "notice", "missing"), [(False, True, "watermark"), (True, False, "notice")])
def test_a_page_missing_one_mark_is_named_for_that_mark(watermark: bool, notice: bool, missing: str) -> None:
    stamped = fill("f1040", {}, "Test")
    one_mark = PdfWriter(clone_from=PdfReader(official("f1040")))
    one_mark.pages[1].merge_page(overlay(612, 792, watermark=watermark, notice=notice).pages[0])
    problems = stamped_problems("f1040", with_page_two(stamped, written(one_mark)))
    assert len(problems) == 1
    assert problems[0].startswith("f1040: page 2 ")
    assert missing in problems[0]


def test_a_value_in_a_field_cannot_stand_in_for_the_watermark() -> None:
    writer = PdfWriter(clone_from=PdfReader(official("f1040")))
    writer.update_page_form_field_values(None, {the_map("f1040")["name"]: WATERMARK}, auto_regenerate=False)
    assert len(stamped_problems("f1040", written(writer))) == 4
