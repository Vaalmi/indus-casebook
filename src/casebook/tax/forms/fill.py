"""Fill an official form from its line-to-field map, and read the filled values back."""

import io
from collections.abc import Mapping
from functools import cache
from typing import cast

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject

from casebook.tax.forms.maps import FormsError, field_map, official_pdf
from casebook.watermark import UNREVIEWED, Marks, stamp_pages

OFF = "/Off"


def _widgets(writer_or_reader: PdfReader | PdfWriter) -> dict[str, DictionaryObject]:
    """Each field, by its fully qualified name. Every field on these forms is a single widget with its own /FT."""
    found: dict[str, DictionaryObject] = {}
    for page in writer_or_reader.pages:
        for annotation in page.get("/Annots", []):
            widget = annotation.get_object()
            if widget.get("/Subtype") != "/Widget":
                continue
            parts: list[str] = []
            node: DictionaryObject | None = widget
            while node is not None:
                if "/T" in node:
                    parts.append(str(node["/T"]))
                parent = node.get("/Parent")
                node = parent.get_object() if parent is not None else None
            found[".".join(reversed(parts))] = widget
    return found


def _field_type(widget: DictionaryObject) -> str:
    return str(widget["/FT"])


def _on_state(widget: DictionaryObject) -> str:
    """A check box's own "on" name (the 1040's filing status boxes are /1 to /5), from its appearances."""
    appearances = cast(DictionaryObject, cast(DictionaryObject, widget["/AP"])["/N"])
    return next(str(state) for state in appearances if state != OFF)


def _max_length(widget: DictionaryObject) -> int | None:
    length = widget.get("/MaxLen")
    return int(length) if length is not None else None


def _checked(form: str, values: Mapping[str, str | bool]) -> dict[str, str | bool]:
    unknown = sorted(set(values) - set(field_map(form)))
    if unknown:
        raise FormsError(f"{form} has no line {', '.join(map(repr, unknown))}; its keys are in maps/{form}.toml")
    return dict(values)


@cache
def _official(form: str) -> PdfReader:
    """The official PDF, parsed once a process: a writer cloned from it copies its objects, so filling one
    copy never changes the next."""
    return PdfReader(io.BytesIO(official_pdf(form)))


def fill(form: str, values: Mapping[str, str | bool], title: str, marks: Marks = UNREVIEWED) -> bytes:
    """The official form with each value in the field its key names, the XFA layer removed, stamped with `marks`.

    Text arrives formatted as it should print; a bool checks or clears a box. The same inputs give the
    same bytes: the fields are set in map order, and the file keeps the official PDF's own /ID.
    """
    values = _checked(form, values)
    writer = PdfWriter(clone_from=_official(form))
    root = writer.root_object
    acro_form = cast(DictionaryObject, root["/AcroForm"].get_object())
    # The XFA layer would take precedence in viewers that read it, showing the form blank. The usage
    # rights signature (/Perms) no longer matches once the file changes, and the document JavaScript
    # only checks for an XFA-capable viewer; the XMP packet repeats the IRS's title and dates.
    del acro_form["/XFA"]
    del root["/Perms"]
    del root["/Names"]
    del root["/Metadata"]
    writer.metadata = {"/Title": title}

    widgets = _widgets(writer)
    fields: dict[str, str] = {}
    for key, name in field_map(form).items():
        if key not in values:
            continue
        value, widget = values[key], widgets[name]
        if _field_type(widget) == "/Btn":
            if not isinstance(value, bool):
                raise FormsError(f"{form} line {key!r} is a check box; give it True or False, not {value!r}")
            fields[name] = _on_state(widget) if value else OFF
        else:
            if isinstance(value, bool):
                raise FormsError(f"{form} line {key!r} holds text; give it a string, not {value!r}")
            limit = _max_length(widget)
            if limit is not None and len(value) > limit:
                raise FormsError(f"{form} line {key!r} holds at most {limit} characters; {value!r} has {len(value)}")
            fields[name] = value
    writer.update_page_form_field_values(None, fields, auto_regenerate=False)
    stamp_pages(writer, marks)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def read_back(form: str, pdf: bytes) -> dict[str, str | bool]:
    """Every mapped key whose field holds a value, as stored: text as written, a checked box as True.

    A blank text field and a cleared box are left out, so a fill's non-blank values read back whole.
    """
    widgets = _widgets(PdfReader(io.BytesIO(pdf)))
    found: dict[str, str | bool] = {}
    for key, name in field_map(form).items():
        widget = widgets.get(name)
        if widget is None:
            raise FormsError(f"{form}: the PDF has no field for line {key!r}")
        value = widget.get("/V")
        if _field_type(widget) == "/Btn":
            if value is not None and str(value) == _on_state(widget):
                found[key] = True
        elif value:
            found[key] = str(value)
    return found
