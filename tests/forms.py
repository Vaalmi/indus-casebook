"""Every form published content takes, for the gate tests (docs/CODE_STANDARDS.md, Lessons: "A gate on published
content misses a form").

In this build's reviews, gates on published content missed 37 forms of what they refuse: an HTML entity, a tag inside
a name, a comment in the page source, a Markdown fence, a zip or a zip in a zip, base64 inside JSON, a JSON list, a
CSV cell, a flattened PDF, a folder not walked, lower or mixed case. Each was fixed for the one form a reviewer
probed. A gate test plants what the gate refuses in every form below, so a gate meets them all the day it is
written, and a new form joins every gate's test at once.

A form is a function from the planted text to the files that carry it, by their path under the folder scanned.
"""

import base64
import csv
import io
import json
from collections.abc import Callable
from html import escape

from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate

from casebook.notice import NOTICE
from casebook.publish.zips import write_zip

Form = Callable[[str], dict[str, bytes]]


def _page(body: str) -> bytes:
    return f"<!doctype html><html><body><main><p>{NOTICE}</p>{body}</main></body></html>".encode()


def _pdf(text: str) -> bytes:
    out = io.BytesIO()
    SimpleDocTemplate(out).build([Paragraph(escape(text), getSampleStyleSheet()["Normal"])])
    return out.getvalue()


def _csv_cell(text: str) -> bytes:
    out = io.StringIO()
    csv.writer(out).writerows([["note"], [text]])
    return out.getvalue().encode()


def _entities(text: str) -> str:
    return "".join(f"&#{ord(c)};" if c.isalnum() else escape(c) for c in text)


def _split_by_tags(text: str) -> str:
    """Every word with a tag inside it, as `Johnson &amp; <strong>Johnson</strong>` reached the site (slice 1)."""
    return " ".join(f"{escape(w[:1])}<span>{escape(w[1:])}</span>" for w in text.split(" "))


FORMS: dict[str, Form] = {
    "a text file": lambda t: {"planted/plain.txt": t.encode()},
    "a file deep in folders": lambda t: {"planted/a/b/c/d/e/deep.txt": t.encode()},
    "a Markdown fence": lambda t: {"planted/notes.md": f"> {NOTICE}\n\n```json\n{t}\n```\n".encode()},
    "a page's visible text": lambda t: {"planted/visible.html": _page(f"<pre>{escape(t)}</pre>")},
    "an HTML comment": lambda t: {"planted/comment.html": _page(f"<!-- {t} -->")},
    "HTML entities": lambda t: {"planted/entities.html": _page(f"<pre>{_entities(t)}</pre>")},
    "a tag inside each word": lambda t: {"planted/tagged.html": _page(f"<p>{_split_by_tags(t)}</p>")},
    "an attribute": lambda t: {"planted/attribute.html": _page(f'<p title="{escape(t)}">-</p>')},
    "a string in a JSON list": lambda t: {
        "planted/list.json": json.dumps({"notice": NOTICE, "rows": [{"debug": [t]}]}).encode()
    },
    "base64 in JSON": lambda t: {
        "planted/blob.json": json.dumps({"notice": NOTICE, "file": base64.b64encode(t.encode()).decode()}).encode()
    },
    "a CSV cell": lambda t: {"planted/cells.csv": _csv_cell(t)},
    "a PDF's text": lambda t: {"planted/flat.pdf": _pdf(t)},
    "a zip member": lambda t: {"planted/packet.zip": write_zip({"NOTICE.txt": NOTICE.encode(), "a.txt": t.encode()})},
    "a zip in a zip": lambda t: {
        "planted/outer.zip": write_zip({"NOTICE.txt": NOTICE.encode(), "inner.zip": write_zip({"a.txt": t.encode()})})
    },
    "lower case": lambda t: {"planted/lower.txt": t.lower().encode()},
    "mixed case": lambda t: {
        "planted/mixed.txt": "".join(c.lower() if i % 2 else c.upper() for i, c in enumerate(t)).encode()
    },
}
