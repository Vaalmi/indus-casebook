"""The gates on published files: the notice, the synthetic label, and no real identifier."""

import csv
import io
import json
from pathlib import Path
from typing import Any

from casebook.model.files import METADATA, SYNTHETIC
from casebook.notice import NOTICE, contains_notice
from casebook.published_text import UnscannableFileError, html_visible_text, text_of
from casebook.securities.scan import RealIdentifierScan, default_scan

PRICE_COLUMN = "price"
PRICE_LABEL_COLUMN = "price_label"


def _files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def notice_problems(site: Path, readme: Path, metadata: Path) -> list[str]:
    problems: list[str] = []
    if not readme.is_file() or not contains_notice(readme.read_text(encoding="utf-8")):
        problems.append(f"{readme.name} lacks the notice")
    for page in (p for p in _files(site) if p.suffix == ".html"):
        if not contains_notice(html_visible_text(page.read_text(encoding="utf-8"))):
            problems.append(f"{page.relative_to(site).as_posix()} lacks the notice")
    try:
        if json.loads(metadata.read_text(encoding="utf-8")).get("notice") != NOTICE:
            problems.append(f"{METADATA} lacks the notice")
    except (OSError, json.JSONDecodeError):
        problems.append(f"{METADATA} is missing or unreadable, so it lacks the notice")
    return problems


def _unlabelled_json_price(value: Any, where: str) -> str | None:
    if isinstance(value, dict):
        if value.get(PRICE_COLUMN) not in (None, "") and value.get(PRICE_LABEL_COLUMN) != SYNTHETIC:
            return where
        for key, child in value.items():
            found = _unlabelled_json_price(child, f"{where}.{key}")
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _unlabelled_json_price(child, f"{where}[{index}]")
            if found:
                return found
    return None


def synthetic_problems(site: Path) -> list[str]:
    """Every price carries the synthetic label: each priced CSV row and JSON object, and any file that shows prices."""
    problems: list[str] = []
    for path in _files(site):
        relative = path.relative_to(site).as_posix()
        if path.suffix == ".csv":
            reader = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))
            if PRICE_COLUMN in (reader.fieldnames or []):
                for line, row in enumerate(reader, start=2):
                    if row[PRICE_COLUMN] and row.get(PRICE_LABEL_COLUMN) != SYNTHETIC:
                        problems.append(f"{relative} line {line}: a price without the {SYNTHETIC!r} label")
                        break
        elif path.suffix == ".json":
            found = _unlabelled_json_price(json.loads(path.read_text(encoding="utf-8")), relative)
            if found:
                problems.append(f"{found}: a price without the {SYNTHETIC!r} label")
        try:
            text = text_of(path.name, path.read_bytes()).lower()
        except UnscannableFileError:
            continue  # real_identifier_problems reports a file no gate can read
        if ("price" in path.name or "price" in text) and SYNTHETIC not in text:
            problems.append(f"{relative}: shows prices without the word {SYNTHETIC!r}")
    return problems


def real_identifier_problems(site: Path, scan: RealIdentifierScan | None = None) -> list[str]:
    scan = scan or default_scan()
    problems: list[str] = []
    for path in _files(site):
        relative = path.relative_to(site).as_posix()
        try:
            text = text_of(path.name, path.read_bytes())
        except UnscannableFileError as error:
            problems.append(str(error))
            continue
        seen: set[tuple[str, str]] = set()
        for hit in scan.find(text):
            shown = " ".join(hit.identifier.split())
            if (hit.kind, shown.lower()) not in seen:
                seen.add((hit.kind, shown.lower()))
                problems.append(f"{relative}: real {hit.kind} {shown!r}")
    return problems


def run_gates(site: Path, readme: Path, metadata: Path) -> list[str]:
    return notice_problems(site, readme, metadata) + synthetic_problems(site) + real_identifier_problems(site)
