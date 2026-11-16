"""The readable text of a file that is about to be published, so the gates can scan it."""

import html
import io
import json
import logging
from html.parser import HTMLParser
from typing import Any

from pypdf import PdfReader

TEXT_SUFFIXES = (".csv", ".json", ".md", ".txt", ".css", ".js")
logging.getLogger("pypdf").setLevel(logging.ERROR)


class UnscannableFileError(ValueError):
    pass


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
    if name.endswith(".json"):
        try:
            return text + "\n" + "\n".join(_json_strings(json.loads(text)))
        except json.JSONDecodeError as error:
            raise UnscannableFileError(f"{name}: not JSON ({error}), so it cannot be scanned") from error
    return text
