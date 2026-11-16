"""docs/PLAN.md, slice 8, on the built book: every featured household's filled return reads back its
inputs, every page carries the watermark and the notice (the build refuses one that does not), and the
site's household pages show the returns."""

import io
import re
import shutil
from pathlib import Path
from typing import cast

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject
from reportlab.pdfgen.canvas import Canvas

from casebook import build
from casebook.build import BuildError, build_book
from casebook.generate.script import load_scripts
from casebook.model.files import event_log_path, read_json, read_manifest
from casebook.model.tax import parse_facts
from casebook.notice import NOTICE
from casebook.publish.site_build import SiteBuildError, build_site
from casebook.tax import forms
from casebook.tax.engine import compute
from casebook.tax.forms.maps import official_pdf
from casebook.tax.forms.returns import return_forms

from .conftest import README, SCRIPTS, SEED, built

RETURNS = re.compile(r"sealed/(HH-\d{4})/returns/(TU-\d{4}-\d)/([\w-]+\.pdf)")


def returns_in(book: Path) -> dict[str, bytes]:
    return {name: (book / name).read_bytes() for name in read_manifest(book).files if RETURNS.fullmatch(name)}


def test_each_filled_form_reads_back_the_values_its_return_holds(book: Path) -> None:
    households = {s.household.household_id: s.household for s in load_scripts(SCRIPTS)}
    filed = returns_in(book)
    expected: set[str] = set()
    for household in built(book):
        for raw in read_json(book, event_log_path(household))["tax_units"]:
            unit = parse_facts(raw)
            for form in return_forms(households[household], unit, compute(unit)):
                name = f"sealed/{household}/returns/{unit.tax_unit_id}/{form.file}"
                expected.add(name)
                assert forms.read_back(form.form, filled := filed[name]) == form.values, name
                assert filled.startswith(b"%PDF")
    # Every featured household files, and the book holds no return beyond the ones the facts call for.
    assert set(filed) == expected
    assert {RETURNS.fullmatch(n).group(1) for n in filed} == set(built(book))  # type: ignore[union-attr]


def test_every_page_of_every_return_carries_the_watermark_and_the_notice(book: Path) -> None:
    filed = returns_in(book)
    assert filed
    for name, pdf in filed.items():
        assert forms.stamped_problems(name, pdf) == [], name


def test_background_households_have_no_return(full_book: Path) -> None:
    background = [h for h in built(full_book) if int(h[3:]) < 1000]
    assert background
    assert not [n for n in read_manifest(full_book).files if RETURNS.fullmatch(n) and n.split("/")[1] in background]


def one_mark_only(watermark: bool) -> bytes:
    """Form 1040's second page with one of the two marks: a page that lacks the other."""
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=(612, 792), invariant=1)
    if watermark:
        canvas.setFont("Helvetica-Bold", 60)
        canvas.drawString(100, 400, forms.WATERMARK)
    else:
        canvas.setFont("Helvetica", 4)
        canvas.drawString(10, 782, NOTICE)
    canvas.save()
    page = PdfWriter(clone_from=PdfReader(io.BytesIO(official_pdf("f1040"))))
    page.pages[1].merge_page(PdfReader(io.BytesIO(buffer.getvalue())).pages[0])
    out = io.BytesIO()
    page.write(out)
    return out.getvalue()


@pytest.mark.parametrize(("watermark", "missing"), [(True, "notice"), (False, "watermark")])
def test_a_return_page_without_the_watermark_or_the_notice_fails_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, watermark: bool, missing: str
) -> None:
    real_fill = forms.fill

    def page_two_unstamped(form: str, values: dict[str, str | bool], title: str) -> bytes:
        filled = real_fill(form, values, title)
        if form != "f1040":
            return filled
        writer = PdfWriter()
        writer.add_page(PdfReader(io.BytesIO(filled)).pages[0])
        writer.add_page(PdfReader(io.BytesIO(one_mark_only(watermark))).pages[1])
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()

    scripts = tmp_path / "scripts" / "archetype-1"
    scripts.mkdir(parents=True)
    shutil.copy(SCRIPTS / "archetype-1" / "HH-1204.toml", scripts)
    monkeypatch.setattr(build.forms, "fill", page_two_unstamped)
    with pytest.raises(BuildError, match=rf"sealed/HH-1204/returns/TU-1204-1/f1040\.pdf: page 2 .*{missing}"):
        build_book(SEED, tmp_path / "book", tmp_path / "scripts")


def test_a_form_that_does_not_read_back_fails_the_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_fill = forms.fill

    def drops_a_value(form: str, values: dict[str, str | bool], title: str) -> bytes:
        return real_fill(form, {k: v for k, v in values.items() if k != "15"}, title)

    scripts = tmp_path / "scripts" / "archetype-1"
    scripts.mkdir(parents=True)
    shutil.copy(SCRIPTS / "archetype-1" / "HH-1204.toml", scripts)
    monkeypatch.setattr(build.forms, "fill", drops_a_value)
    with pytest.raises(BuildError, match=r"f1040\.pdf: its fields do not read back as filled"):
        build_book(SEED, tmp_path / "book", tmp_path / "scripts")


def test_featured_household_pages_show_their_returns(book: Path, site: Path) -> None:
    for household in built(book):
        page = (site / "households" / f"{household}.html").read_text()
        assert 'data-section="return"' in page, household
        links = re.findall(r'href="\.\./(data/[^"]+/sealed/' + household + r'/returns/[^"]+\.pdf)"', page)
        assert links, household
        for link in links:
            assert (site / link).is_file(), link
    hh_3058 = (site / "households" / "HH-3058.html").read_text()
    for label in ("Form 1040", "Schedule B", "Schedule D", "Form 8949, box A, page 1", "Form 8960", "Form 8959"):
        assert f">{label}</a>" in hh_3058, label
    assert ">Form 8606, Luka Kovac</a>" in (site / "households" / "HH-1204.html").read_text()


def edited_stamp(pdf: bytes, old: bytes, new: bytes) -> bytes:
    """The form with one operator in its second page's stamp changed."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    stream = cast(ArrayObject, writer.pages[1]["/Contents"].get_object())[-1].get_object()
    data = stream.get_data()
    assert old in data
    stream.set_data(data.replace(old, new))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.mark.parametrize(
    ("old", "new", "mark"),
    [
        (b"1 Tr", b"3 Tr", "watermark"),  # reviewer B, slice 8 round 1: an invisible render mode
        (b"0.619608 0.619608 0.619608 RG", b"1 1 1 RG", "watermark"),  # white on white
        (b"/F1 5 Tf", b"/F1 0.5 Tf", "notice"),  # too small to read
    ],
)
def test_a_mark_present_as_text_but_not_shown_fails_the_stamp_check(old: bytes, new: bytes, mark: str) -> None:
    pdf = edited_stamp(forms.fill("f1040", {"1a": "1,000.00"}, "Test"), old, new)
    shown = "notice" if mark == "notice" else f"{forms.WATERMARK!r} watermark"
    assert forms.stamped_problems("f1040.pdf", pdf) == [f"f1040.pdf: page 2's {shown} is not drawn so that it shows"]


def test_the_site_refuses_a_return_damaged_after_the_build(book_copy: Path, tmp_path: Path) -> None:
    """Reviewers A and B, slice 8 round 1: a return whose second page lost its stamp after the build is
    caught by the site's gates, not published."""
    name = "sealed/HH-1204/returns/TU-1204-1/f1040.pdf"
    filled = (book_copy / name).read_bytes()
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(filled)))
    cast(ArrayObject, writer.pages[1]["/Contents"].get_object()).pop()  # drop the stamp, keep the form and fields
    out = io.BytesIO()
    writer.write(out)
    (book_copy / name).write_bytes(out.getvalue())
    with pytest.raises(SiteBuildError, match=r"returns/TU-1204-1/f1040\.pdf: page 2 has no 'UNREVIEWED' watermark"):
        build_site(book_copy, tmp_path / "site", README)
