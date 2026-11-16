"""The readable text of a file that is about to be published, so the gates can scan it."""

import base64
import binascii
import html
import io
import json
import logging
import re
from html.parser import HTMLParser
from typing import Any

from pypdf import PdfReader

TEXT_SUFFIXES = (".csv", ".json", ".jsonl", ".md", ".txt", ".css", ".js")
logging.getLogger("pypdf").setLevel(logging.ERROR)


class UnscannableFileError(ValueError):
    pass


_BASE64 = re.compile(r"[A-Za-z0-9+/]+={0,2}")
BLOB_MIN = 64


def decoded_blob(value: str) -> str | None:
    """The readable text inside a base64 string (a PDF's text, or decoded UTF-8), or None if it is not one.

    Transcripts carry the files a run read, PDFs among them, as base64; their text must be
    scanned like any other published text.
    """
    if len(value) < BLOB_MIN or len(value) % 4 or not _BASE64.fullmatch(value):
        return None
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    if data.startswith(b"%PDF"):
        try:
            return "\n".join(pdf_pages_text(data))
        except Exception as error:  # an unreadable PDF must not pass the gate unread
            raise UnscannableFileError(f"an embedded PDF cannot be read ({error})") from error
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        for name, value in attrs:
            if value and name in ("title", "alt", "aria-label", "content", "href", "src"):
                self.parts.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_visible_text(html: str, separator: str = " ") -> str:
    parser = _Text()
    parser.feed(html)
    return separator.join(parser.parts)


def pdf_pages_text(data: bytes) -> list[str]:
    return [page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages]


def _json_strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (str(k), *_json_strings(v))]
    if isinstance(value, list):
        return [s for item in value for s in _json_strings(item)]
    if isinstance(value, str):
        blob = decoded_blob(value)
        return [value] if blob is None else [value, blob]
    return [str(value)] if value is not None else []


def text_of(name: str, data: bytes) -> str:
    """All the text in a file, raw and decoded, for the real-identifier scan.

    Markup and attributes count, and so does what an escape decodes to: `Johnson &amp; Johnson`
    shows on the page as a real name.
    """
    if name.endswith(".pdf"):
        return "\n".join(pdf_pages_text(data))
    if not name.endswith((".html", *TEXT_SUFFIXES)):
        raise UnscannableFileError(f"{name}: no way to read this file's text, so it cannot be published")
    text = data.decode("utf-8")
    if name.endswith(".html"):
        # Tags inside a name do not split it on the page: `Johnson &amp; <b>Johnson</b>` reads as one name.
        # Joined with nothing, the rendered text keeps such names whole; joined with spaces, it keeps a
        # ticker in one cell apart from the next.
        return "\n".join((text, html.unescape(text), html_visible_text(text, ""), html_visible_text(text, " ")))
    if name.endswith((".json", ".jsonl")):
        documents = [text] if name.endswith(".json") else [line for line in text.splitlines() if line.strip()]
        try:
            decoded = [s for document in documents for s in _json_strings(json.loads(document))]
        except json.JSONDecodeError as error:
            raise UnscannableFileError(f"{name}: not JSON ({error}), so it cannot be scanned") from error
        return text + "\n" + "\n".join(decoded)
    return text
