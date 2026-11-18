"""What every key shares: a figure the key computes, which an answer may cite (the fabricated-figure rule
accepts it within a dollar), and the 2025 Forms W-2 the household's documents hold."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from casebook.model.files import DOCUMENTS_INDEX, read_json
from casebook.model.money import parse_decimal

W2 = "form_w2"
# Form W-2 box 1, as the custodian's copy on file prints it.
_BOX_1 = re.compile(r"Box 1 Wages, tips, other compensation: \$([\d,]+\.\d{2})")


@dataclass(frozen=True)
class KeyFigure:
    label: str
    value: Decimal


@dataclass(frozen=True)
class W2Wages:
    person_id: str
    file: str
    box_1: Decimal | None  # None when the form shows no box 1


def w2_wages(root: Path, year_end: date) -> tuple[W2Wages, ...]:
    """Each Form W-2 for the year ending `year_end` in the household's documents, with its box 1 as printed."""
    found: list[W2Wages] = []
    for doc in read_json(root, DOCUMENTS_INDEX)["documents"]:
        if doc["kind"] != W2 or str(doc["valuation_date"]) != year_end.isoformat():
            continue
        text = "\n".join(page.extract_text() or "" for page in PdfReader(root / "documents" / str(doc["file"])).pages)
        box = _BOX_1.search(text)
        wages = parse_decimal(box.group(1).replace(",", "")) if box else None
        found.append(W2Wages(str(doc["person_id"]), str(doc["file"]), wages))
    return tuple(found)
