"""The gates on published files: the notice, the synthetic label, no real identifier, the watermark
and notice on every page of a filled return, and nothing of a held task's verdict."""

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

from casebook.model.files import METADATA, SYNTHETIC
from casebook.notice import NOTICE, contains_notice
from casebook.publish.private_set import private_set_problems
from casebook.published_text import UnscannableFileError, html_visible_text, text_of
from casebook.securities.scan import RealIdentifierScan, default_scan
from casebook.watermark import stamped_problems

PRICE_COLUMN = "price"
PRICE_LABEL_COLUMN = "price_label"
# A price written in a record's prose: an amount a share or a unit, or "price" before an amount.
_PROSE_PRICE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?\s+(?:a|per|each)\s+(?:share|unit)\b|\bprice[sd]?\b[^$.\n]{0,20}\$\s?\d",
    re.IGNORECASE,
)


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
        # CSV and JSON carry their prices in fields, checked row by row above; in their free text a
        # price is one written as a price ("$216.06 a share", "priced at $40"), not the word in a
        # name. Pages and documents are read as text.
        structured = path.suffix in (".csv", ".json")
        shows = _PROSE_PRICE.search(text) is not None if structured else "price" in text
        if ("price" in path.name or shows) and SYNTHETIC not in text:
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


def return_problems(site: Path) -> list[str]:
    """Every page of every filled return the site would publish carries the watermark and the notice,
    drawn so that they show (SPEC: "Filled returns: shown ... with an 'unreviewed' watermark on every
    page"). A return damaged after the build is caught here, before it is published."""
    problems: list[str] = []
    for pdf in (p for p in _files(site) if p.suffix == ".pdf" and "/returns/" in p.as_posix()):
        problems += stamped_problems(pdf.relative_to(site).as_posix(), pdf.read_bytes())
    return problems


# A run record's states once the mapper has run on it: a graded run is mapped, then published; a failed run is
# mapped and stays failed (docs/PLAN.md, the run's state table).
MAPPED_STATES = ("mapped", "published", "failed")


def unmapped_record_problems(runs: Path) -> list[str]:
    """Every run record among the published runs that ran on real tickers and never passed the mapper: its
    unmapped form belongs under `$CASEBOOK_PRIVATE` only (docs/SPEC.md: "Published run outputs and run records
    show aliases"). Every record, at any depth (reviewer A, slice 13 round 1)."""
    problems: list[str] = []
    for path in sorted(runs.rglob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if (record.get("dataset") or {}).get("real_tickers") and record.get("state") not in MAPPED_STATES:
            problems.append(
                f"{path.relative_to(runs).as_posix()}: an unmapped run record (state {record.get('state')!r}), "
                "which stays under $CASEBOOK_PRIVATE"
            )
    return problems


# A published run's files, as `casebook run` writes them: `<task>/<run id>.json` and its transcript beside it, the
# run ID beginning with the task's.
_RUN_FILE = re.compile(r"(?P<task>[A-Z]-[A-Z]{3}-\d{2})/(?P=task)-[A-Za-z0-9-]+(?:\.json|\.transcript\.jsonl)")


def run_layout_problems(runs: Path) -> list[str]:
    """Every file under the published runs that is not a run's record or transcript where `casebook run` writes it:
    the site copies the whole folder, so a file elsewhere would be published past the gates that read run records
    (reviewer A, slice 13 round 1)."""
    problems = [
        f"{relative}: not <task>/<run id>.json or <task>/<run id>.transcript.jsonl"
        for relative in (p.relative_to(runs).as_posix() for p in _files(runs))
        if not _RUN_FILE.fullmatch(relative)
    ]
    # A record filed under another task's folder or name would be shown on that task's page but published, and
    # gated, under this one (reviewer A, slice 14 round 1).
    for path in sorted(runs.glob("*/*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("task_id") != path.parent.name or record.get("run_id") != path.stem:
            problems.append(
                f"{path.relative_to(runs).as_posix()}: names task {record.get('task_id')!r} and run "
                f"{record.get('run_id')!r}, not the folder and file it is filed under"
            )
    return problems


# What a held task's page never shows before the tax review: "sources and outputs only, with no verdict and no
# failure marking" (docs/SPEC.md), "and no explanation of the task's expected output" (docs/PLAN.md, U4). The page's
# own words are read; the prompt, each arm's output and what a run wrote to the CRM sandbox are the task's and the
# model's, and may say anything.
_QUOTED = re.compile(r'<pre class="(?:prompt|output)">.*?</pre>|<details data-section="crm-diff">.*?</details>', re.S)
_VERDICT_MARKUP = re.compile(r'data-outcome="(?!held")[^"]*"|data-verdict="(?!held")[^"]*"')
_VERDICT_TEXT = re.compile(r"\b(?:passed|failed)\s*[:,]\s*\d|\b\d{1,3} of 100\b|critical fail|graded again", re.I)
_MARKING = re.compile(r'data-criterion=|class="(?:hit|miss)"')
_MARKS = re.compile(r"[\u2713\u2714\u2717\u2718]")  # check and cross marks, however the page writes them
_EXPLANATION = re.compile(r'data-section="justified-conclusion"')
_EXPLANATION_TEXT = re.compile(r"justified conclusion", re.I)
# As much of a held task's justified conclusion as shows it was copied in.
_CONCLUSION_SHOWN = 60


def held_page_problems(site: Path, held: dict[str, str], runs: Path | None = None) -> list[str]:
    """Every held task's page and published run records: no verdict, no failure marking, no explanation of the
    expected output. `held`: each held task's ID and its justified conclusion. The page's words are read as a
    visitor sees them, entities decoded; a record is a held task's by its folder or by the task it names (reviewers
    A and B, slice 14 round 1). `runs`: the run records' folder, the site's own (`data/runs`) by default; a release
    also ships them beside the site."""
    problems: list[str] = []
    for task_id, conclusion in sorted(held.items()):
        page = site / "tasks" / f"{task_id}.html"
        if page.is_file():
            own = _QUOTED.sub(" ", page.read_text(encoding="utf-8"))
            text = " ".join(html_visible_text(own).split())
            where = page.relative_to(site).as_posix()
            if _VERDICT_MARKUP.search(own) or _VERDICT_TEXT.search(text):
                problems.append(f"{where}: a held task's page shows a verdict")
            if _MARKING.search(own) or _MARKS.search(text):
                problems.append(f"{where}: a held task's page marks a failure")
            shown = " ".join(conclusion.split())[:_CONCLUSION_SHOWN]
            if _EXPLANATION.search(own) or _EXPLANATION_TEXT.search(text) or (shown and shown in text):
                problems.append(f"{where}: a held task's page explains its expected output")
    for record in sorted((runs or site / "data" / "runs").rglob("*.json")):
        data = json.loads(record.read_text(encoding="utf-8"))
        if record.parent.name not in held and data.get("task_id") not in held:
            continue
        if data.get("grade") is not None or (data.get("regraded") or {}).get("grade_before") is not None:
            where = record.relative_to(site if runs is None else runs.parent).as_posix()
            problems.append(f"{where}: a held task's run record carries its grade")
    return problems


def run_gates(site: Path, readme: Path, metadata: Path, held: dict[str, str] | None = None) -> list[str]:
    return (
        notice_problems(site, readme, metadata)
        + synthetic_problems(site)
        + real_identifier_problems(site)
        + return_problems(site)
        + private_set_problems(site)
        + held_page_problems(site, held or {})
    )
