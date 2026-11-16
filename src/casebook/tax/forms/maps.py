"""The official 2025 IRS PDFs and each one's line-to-field map, as package data."""

import tomllib
from collections.abc import Mapping
from functools import cache
from importlib.resources import files

FORMS: tuple[str, ...] = (
    "f1040",
    "f1040s1",
    "f1040s1a",
    "f1040s2",
    "f1040s3",
    "f1040sa",
    "f1040sb",
    "f1040sd",
    "f8949",
    "f8606",
    "f8960",
    "f8959",
)
TAX_YEAR_SUFFIX = "--2025.pdf"
_DATA = files("casebook.tax.forms")


class FormsError(Exception):
    """A form, or a value for one of its lines, the filler cannot take."""


def _known(form: str) -> str:
    if form not in FORMS:
        raise FormsError(f"no official form {form!r}; the forms are {', '.join(FORMS)}")
    return form


@cache
def official_pdf(form: str) -> bytes:
    """The official PDF, byte for byte as the IRS published it."""
    return (_DATA / "pdfs" / f"{_known(form)}{TAX_YEAR_SUFFIX}").read_bytes()


@cache
def field_map(form: str) -> Mapping[str, str]:
    """Each key the form's map defines, with the fully qualified name of the PDF field that holds it."""
    text = (_DATA / "maps" / f"{_known(form)}.toml").read_text(encoding="utf-8")
    return dict(tomllib.loads(text)["fields"])


def keys(form: str) -> frozenset[str]:
    return frozenset(field_map(form))
