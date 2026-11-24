"""The preview release's gates: what `casebook release --preview` refuses to ship (docs/PLAN.md, slice 16).

A release bundle fails on: a tax or RMD answer key, a tax answer sheet or a verdict on a tax-lot or RMD task; a
combined score; a household with a failed check; a real ticker or security name; a private task, fixture or key; a
filled-form page with no watermark; a file with no notice; a result with no tool, version, model or date; anything
from `out/real/`; and a home-folder path (the owner's decision of 19 November 2026,
docs/decisions/2026-11-19-slice16-release-choices.md, choices 2 and 5a). It also fails on any file the release does
not put where it sits (`layout_problems`): what is not one of the release's own files does not ship, whatever it holds
(reviewers A and B, slice 16 round 1).

The gate tells held material from what may ship by where it comes from (docs/PLAN.md, "What stays held for tax and
RMD"): each held task's key, computed here as the runner computes it on both builds, and a household's tax summary are
refused by their bytes, and by their content wherever it is copied into a JSON document; the registry's justified
conclusions are not.

Every file of the bundle is read, and every member of every zip in it. The bundle is read through a scan tree, a
folder of links to its files in which each zip is unpacked into a folder named for it with a `!`, so the gates that
read a folder read the members too, and a member is named as `packets/HH-4821.zip!households/...`.
"""

import csv
import dataclasses
import hashlib
import io
import json
import posixpath
import re
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import cache, lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

from pypdf import PdfReader
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import simpleSplit

from casebook.checks import check_book
from casebook.graders.registry import grader
from casebook.model.files import (
    ALIASES,
    MANIFEST,
    METADATA,
    PRICES_CSV,
    SEALED_HOUSEHOLDS,
    SECURITIES_CSV,
    TAX_SUMMARY,
    FileFormatError,
    Manifest,
    is_tax_summary,
    json_text,
    read_manifest,
)
from casebook.notice import NOTICE, contains_notice
from casebook.publish.gates import (
    held_page_problems,
    real_identifier_problems,
    run_layout_problems,
    synthetic_problems,
    unmapped_record_problems,
)
from casebook.publish.packets import TAX_ANSWER_SHEET
from casebook.publish.private_set import private_set_problems
from casebook.publish.zips import ZipError, read_zip
from casebook.published_text import UnscannableFileError, html_visible_text, pdf_pages_text, text_of
from casebook.review_statement import (
    REVIEW_STATEMENT,
    ReviewStatement,
    household_of,
    is_held,
    is_reviewed,
    return_marks,
    statement_of,
)
from casebook.site import FEATURED, data_root
from casebook.site.results import private_outcomes_problems
from casebook.site.tasks import UnnamedResultError, require_named
from casebook.sources.pdf import FOOTER_SIZE, MARGIN
from casebook.tasks import task as task_files
from casebook.watermark import Marks, stamped_problems

NOTICE_FILE = "NOTICE.txt"
ZIP_MARK = "!"
BOOK = "book"
SITE = "site"
RUNS = "runs"
RESULTS = "results"
KEYS = "keys"
SITE_RUNS = "data/runs"
HOUSEHOLDS = "households"
PACKETS = "packets"
IMAGES = "docs/images"
RETURNS = "returns"
DOCUMENTS = "documents"
# The book's own JSON: what a build writes under these folders, and its manifest and metadata. It cannot carry the
# notice without changing book bytes, so the metadata.json or NOTICE.txt of the folder it ships in covers it.
BOOK_FOLDERS = frozenset({HOUSEHOLDS, "securities", "sealed"})
# A book file at its root, covered by its metadata.json like the rest: the review statement too (reviewers A and B,
# slice 17 round 1, S1).
BOOK_FILES = frozenset({MANIFEST, METADATA, REVIEW_STATEMENT})
# The document PDFs' footer as sources/pdf.py wraps it. It is drawn bottom-up, so pypdf reads its lines out of
# order and the notice is not one run of text: each line must be there.
FOOTER_LINES = tuple(simpleSplit(NOTICE, "Helvetica", FOOTER_SIZE, LETTER[0] - 2 * MARGIN))

# A combined score is structure, not words: the results page says "there is no combined score".
_SCORE_WORDS = r"(?:combined|overall|aggregate|total|mean|average)[\s_-]*scores?"
_SCORE_KEY = re.compile(r"(?:combined|overall|aggregate|total|mean|average)[_-]?scores?", re.I)
_SCORE_SHOWN = re.compile(
    rf"\b{_SCORE_WORDS}\b\W{{0,3}}(?:(?:is|was|of)\s+)?\d|\d[\d.,]*\s*%?\s*(?:/\s*\d+\s*)?\(?\s*{_SCORE_WORDS}\b", re.I
)
# A path in someone's home folder (choice 5a); not the same words inside a URL or a longer path.
_HOME = re.compile(r"(?<![\w.~/-])(?:/Users/[^/\s\"'<>]+/|/home/[^/\s\"'<>]+/)|(?<!\w)[A-Za-z]:\\+Users\\+", re.I)

# The bundle's layout, as `_stage` in release.py writes it: every file the release puts there, and nothing else.
TOP_FILES = frozenset(
    {"README.md", "LICENSE", "LICENSE-DATA", NOTICE_FILE, "release.json", "errata.json", "freeze.json"}
)
FIXED_FILES = frozenset(
    {
        f"{RESULTS}/private-outcomes.json",
        "audit/audit-log.csv",
        "audit/AUDIT.md",
        f"audit/{NOTICE_FILE}",
        f"{KEYS}/{NOTICE_FILE}",
        f"{SITE}/{NOTICE_FILE}",
        f"{IMAGES}/{NOTICE_FILE}",
    }
)
_SITE_PAGE = re.compile(r"(?:(?:tasks|households)/)?[^/]+\.html")
_PACKET_ZIP = re.compile(r"(?P<household>HH-\d{4})\.zip")
# A case packet's members (publish/packets.py): its household's source sets, the shared securities files and metadata,
# its notice and its answer sheet.
PACKET_FILES = frozenset({SECURITIES_CSV, PRICES_CSV, METADATA, NOTICE_FILE, "answer-sheet.json", TAX_ANSWER_SHEET})
SOURCE_SETS = ("custodian", "portfolio", "crm", DOCUMENTS)
# Where a PDF may sit: a household's documents and a sealed return, in the book and in the site's copy of it.
_BOOK_PDF = re.compile(rf"{HOUSEHOLDS}/HH-\d{{4}}/{DOCUMENTS}/.+\.pdf|sealed/HH-\d{{4}}/{RETURNS}/.+\.pdf")


@dataclass(frozen=True)
class HeldMaterial:
    """What the preview release never ships, and the little it ships that the gate cannot read. `tasks`: each held
    task's ID and its justified conclusion. `answers`: the sha256 of each held key's and each tax summary's bytes,
    and of its content as canonical JSON less any notice. `real_only`: the sha256 of each file of the real-ticker
    build that the default build does not have. `open_tasks`: the public tasks that are not held, whose keys ship.
    `images`: the sha256 of each of the README's committed PNG screenshots, by file name. `statement`: the review
    statement the book was built under, if any; `reviewed`: the tax tasks its scope names, whose keys and pages carry
    the reviewed notice."""

    tasks: dict[str, str]
    answers: frozenset[str]
    real_only: frozenset[str]
    open_tasks: frozenset[str]
    images: dict[str, str]
    statement: ReviewStatement | None = None
    reviewed: frozenset[str] = frozenset()
    # The tax answer sheet of each household the statement covers, as canonical JSON less its notice: the one a case
    # packet may ship, its own household's and no other (reviewer B, slice 17 round 2, D3).
    tax_sheets: dict[str, str] = dataclasses.field(default_factory=dict[str, str])

    def notice_of(self, name: str) -> str:
        """The notice a file must carry: the reviewed notice on a reviewed tax task's key or page, and on the tax
        answer sheet of a household a review statement covers; else the notice."""
        if self.statement is None:
            return NOTICE
        task = _TASK_FILE.search(name)
        if task is not None and task.group(1) in self.reviewed:
            return self.statement.notice
        if name.endswith(f"{ZIP_MARK}{TAX_ANSWER_SHEET}") and self.statement.covers_return(household_of(name)):
            return self.statement.notice
        return NOTICE

    def marks_of(self, name: str) -> Marks:
        """The watermark and notice on every page of a return: the reviewed ones on a household the statement covers."""
        return return_marks(household_of(name), self.statement)


# A task's own file: its key (`keys/T-TAX-01.json`) or its page (`site/tasks/T-TAX-01.html`).
_TASK_FILE = re.compile(r"(?:^|/)(?:keys|tasks)/(T-[A-Z]+-\d{2})\.(?:json|html)$")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _folded(value: Any) -> Any:
    """A parsed JSON value with every key and string case-folded and its spacing taken out."""
    if isinstance(value, str):
        return "".join(value.split()).casefold()
    if isinstance(value, dict):
        return {_folded(k): _folded(v) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, list):
        return [_folded(v) for v in value]  # pyright: ignore[reportUnknownVariableType]
    return value


def _canonical(value: Any) -> str:
    """The digest of a parsed JSON value written canonically, a top-level notice left out, its letters folded to one
    case and its spacing taken out: a held key copied with a notice added, re-spaced, wrapped across a PDF's lines or
    re-cased is still the key (the `correct` pass, 23 November 2026: tests/forms.py)."""
    if isinstance(value, dict):
        value = {k: v for k, v in value.items() if k != "notice"}  # pyright: ignore[reportUnknownVariableType]
    return _digest(json.dumps(_folded(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def _book_files(book: Path) -> dict[str, bytes]:
    return {name: (book / name).read_bytes() for name in read_manifest(book).files}


def _key_bytes(task: task_files.Task, book: Path) -> bytes:
    """A task's key as `casebook run` computes and writes it (runner/session.py, `write_key`)."""
    return json_text(grader(task.grader).key(book, task.household_id, task.grader_params).to_dict()).encode()


def held_material(book: Path, real_book: Path | None, tasks: Path, held_keys: Path, images: Path) -> HeldMaterial:
    """`book`: the default build; `real_book`: the real-ticker build (out/real/<version>), if there is one; `tasks`:
    the public task files; `held_keys`: where `casebook run` writes held keys (out/keys), under the book's version;
    `images`: the repo's docs/images, the README's committed images.

    Each held task's key is computed here on both builds, as the runner computes it, so a fresh clone with no
    out/keys/ still knows it (reviewers A and B, slice 16 round 1); a key in out/keys/ counts as well."""
    loaded = [task_files.load_task(path) for path in sorted(tasks.glob("T-*.toml"))]
    # A tax task a review statement covers is released: its key and verdict ship (docs/PLAN.md, slice 17).
    statement = statement_of(book)
    held_tasks = [t for t in loaded if is_held(t, statement)]
    version = read_manifest(book).version
    builds = [book, *([real_book] if real_book is not None else [])]
    answers = [_key_bytes(task, build) for task in held_tasks for build in builds]
    keys = [held_keys / version / f"{task.task_id}.json" for task in held_tasks]
    answers += [key.read_bytes() for key in keys if key.is_file()]
    default = _book_files(book)
    real = _book_files(real_book) if real_book is not None else {}
    # A tax answer sheet a review statement covers ships in its household's case packet (slice 17, round 1, S2).
    answers += [
        data
        for files in (default, real)
        for name, data in files.items()
        if is_tax_summary(name) and not (statement is not None and statement.covers_return(household_of(name)))
    ]
    digests = {_digest(a) for a in answers} | {_canonical(json.loads(a)) for a in answers}
    real_only = {_digest(d) for d in real.values()} - {_digest(d) for d in default.values()}
    return HeldMaterial(
        tasks={t.task_id: t.justified_conclusion for t in held_tasks},
        answers=frozenset(digests),
        real_only=frozenset(real_only),
        open_tasks=frozenset(t.task_id for t in loaded if not is_held(t, statement)),
        images={p.name: _digest(p.read_bytes()) for p in sorted(images.glob("*.png"))},
        statement=statement,
        reviewed=frozenset(t.task_id for t in loaded if is_reviewed(t, statement)),
        tax_sheets={
            household_of(name): _canonical(json.loads(data))
            for name, data in default.items()
            if is_tax_summary(name) and statement is not None and statement.covers_return(household_of(name))
        },
    )


# The scan tree.


def _scan_tree(bundle: Path, tree: Path) -> tuple[list[str], list[str]]:
    """Link every file of `bundle` into `tree`, unpacking each zip (and each zip in a zip) into a folder named for
    it with a `!`. Returns the zips' folders in the tree, and a problem for each zip that cannot be read."""
    roots: list[str] = []
    problems: list[str] = []
    for path in sorted(p for p in bundle.rglob("*") if p.is_file()):
        relative = path.relative_to(bundle).as_posix()
        if path.suffix == ".zip":
            _unpack(relative, path.read_bytes(), tree, roots, problems)
            continue
        target = tree / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(path.resolve())
    return roots, problems


def _unpack(name: str, data: bytes, tree: Path, roots: list[str], problems: list[str]) -> None:
    try:
        members = read_zip(data)
    except ZipError as error:
        problems.append(f"{_shown(name)}: an unreadable zip ({error})")
        return
    root = name + ZIP_MARK
    roots.append(root)
    (tree / root).mkdir(parents=True, exist_ok=True)
    for member, content in members.items():
        if member.endswith(".zip"):
            _unpack(f"{root}/{member}", content, tree, roots, problems)
            continue
        target = tree / root / member
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _shown(name: str) -> str:
    """A path in the scan tree as the release names it: a zip member as `packets/HH-4821.zip!households/...`."""
    return name.replace(ZIP_MARK + "/", ZIP_MARK)


def _root_of(name: str, roots: list[str]) -> str:
    """The zip a file of the scan tree is a member of (its folder in the tree), or "" for the bundle's own."""
    return max((r for r in roots if name.startswith(r + "/")), key=len, default="")


# One file's problems.


def _json_documents(name: str, data: bytes) -> list[Any]:
    text = data.decode("utf-8")
    if name.endswith(".jsonl"):
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return [json.loads(text)]


def _walk(value: Any) -> Iterator[tuple[str, Any]]:
    """Every key of every object at any depth, with its value."""
    if isinstance(value, dict):
        for key, child in value.items():  # pyright: ignore[reportUnknownVariableType]
            yield str(key), child  # pyright: ignore[reportUnknownArgumentType]
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:  # pyright: ignore[reportUnknownVariableType]
            yield from _walk(child)


def _objects(value: Any) -> Iterator[Any]:
    """The value, if it is an object, and every object inside it at any depth, a list's elements among them."""
    if isinstance(value, dict):
        yield value
        children: Any = value.values()  # pyright: ignore[reportUnknownMemberType]
    elif isinstance(value, list):
        children = value
    else:
        return
    for child in children:
        yield from _objects(child)


def _graded(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    regraded: Any = record.get("regraded") or {}  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    return record.get("grade") is not None or regraded.get("grade_before") is not None  # pyright: ignore[reportUnknownMemberType]


def _is_record(document: Any) -> bool:
    """A run record's shape: an object naming its run and its task."""
    return isinstance(document, dict) and "run_id" in document and "task_id" in document


def _record_problems(name: str, records: list[dict[str, Any]], held: HeldMaterial) -> list[str]:
    """A run record outside the two run folders: refused for where it sits, and held to the checks the records in
    them pass (reviewers A and B, slice 16 round 1), so its other faults are named too."""
    problems = [f"{name}: a run record outside {RUNS}/ and {SITE}/{SITE_RUNS}/"]
    if any(r.get("task_id") in held.tasks and _graded(r) for r in records):
        problems.append(f"{name}: a held task's run record carries its grade")
    for record in records:
        try:
            require_named(record, name)
        except UnnamedResultError as error:
            problems.append(str(error))
    return problems


def _json_problems(name: str, documents: list[Any], held: HeldMaterial, in_zip: bool) -> list[str]:
    problems: list[str] = []
    scores = sorted({k for d in documents for k, _ in _walk(d) if _SCORE_KEY.fullmatch(k)})
    if scores:
        problems.append(f"{name}: a combined score ({', '.join(scores)})")
    if any(_canonical(o) in held.answers for d in documents for o in _objects(d)):
        problems.append(f"{name}: holds a held task's answer key or a tax answer sheet")
    # The records at the top of a file in the two run folders are read by held_page_problems and _result_problems;
    # any other is read here, a record nested inside another file's JSON at any depth among them (reviewer B,
    # slice 16 round 2, S3: a graded held record under an extra field of a published key shipped).
    in_runs = not in_zip and name.startswith((f"{RUNS}/", f"{SITE}/{SITE_RUNS}/"))
    records = [o for d in documents for o in _objects(d) if _is_record(o) and not (in_runs and o is d)]
    if records:
        problems += _record_problems(name, records, held)
    if PurePosixPath(name).name == METADATA and isinstance(documents[0], dict):
        securities = documents[0].get("securities")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if securities != ALIASES:
            problems.append(f"{name}: the metadata of a build whose securities are {securities!r}, not {ALIASES!r}")
    return problems


def _scanned_text(name: str, data: bytes) -> str:
    try:
        return text_of(name, data)
    except UnscannableFileError:
        return data.decode("utf-8", errors="ignore")  # real_identifier_problems reports a file no gate can read


# A release ships each PDF in the book and again in the site's copy of it: each is read once.
@lru_cache(maxsize=1024)
def _is_filled_form(data: bytes) -> bool:
    return "/AcroForm" in PdfReader(io.BytesIO(data)).root_object


@lru_cache(maxsize=1024)
def _stamp_problems(data: bytes, marks: Marks) -> tuple[str, ...]:
    """stamped_problems of a PDF, each line without the file's name."""
    return tuple(stamped_problems("", data, marks))


def _is_stamped_pdf(name: str, data: bytes) -> bool:
    """A PDF that must carry the watermark and the notice on every page: one under any `returns/` folder, a zip's
    among them, and any with a form, wherever it sits. A flattened return has no form (reviewer B, slice 16 round 1)."""
    return name.endswith(".pdf") and (RETURNS in re.split(rf"[/{ZIP_MARK}]", name)[:-1] or _is_filled_form(data))


def _csv_score_problems(name: str, data: bytes) -> list[str]:
    """A CSV column named for a combined score (reviewer B, slice 16 round 1)."""
    header = next(csv.reader(io.StringIO(data.decode("utf-8", errors="replace"))), [])
    scores = sorted({h.strip() for h in header if re.fullmatch(_SCORE_WORDS, h.strip(), re.I)})
    return [f"{name}: a combined score ({', '.join(scores)})"] if scores else []


# Not strict: a string wrapped across a PDF's lines holds a line break.
_DECODER = json.JSONDecoder(strict=False)


def _embedded_json(text: str) -> list[Any]:
    """Every JSON object written out whole inside a text: a key pasted into a README's code block, say (whole-branch
    review, reviewer B)."""
    found: list[Any] = []
    start = text.find("{")
    while start != -1:
        try:
            value, end = _DECODER.raw_decode(text, start)
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        found.append(value)
        start = text.find("{", end)
    return found


def _text_views(name: str, data: bytes) -> list[str]:
    """Every text a file holds: what the shared reader gives (raw, its markup's entities
    decoded, as a page shows it with and without breaks between tags, every JSON string and every base64 blob decoded,
    a PDF's text and fields), and a CSV's cells unquoted."""
    views = [_scanned_text(name, data)]
    if name.endswith(".csv"):
        rows = csv.reader(io.StringIO(data.decode("utf-8", errors="replace")))
        views.append("\n".join(cell for row in rows for cell in row))
    return views


def _file_problems(name: str, data: bytes, held: HeldMaterial, in_zip: bool) -> list[str]:
    problems: list[str] = []
    digest = _digest(data)
    if digest in held.answers:
        problems.append(f"{name}: a held task's answer key or a tax answer sheet")
    if PurePosixPath(name).name == TAX_SUMMARY:
        problems.append(f"{name}: a tax summary, a tax answer sheet held until the tax review")
    if digest in held.real_only:
        problems.append(f"{name}: a file of the real-ticker build (out/real/)")
    # The run records this file holds as JSON, which the record checks read, by their whole content: only the very same
    # record found again in the file's text is left to them (reviewers A and B, slice 17 round 2, S3: by its run ID
    # alone, a graded copy of a record hid inside the record).
    structured: set[str] = set()
    if name.endswith((".json", ".jsonl")):
        try:
            documents = _json_documents(name, data)
            problems += _json_problems(name, documents, held, in_zip)
            structured = {_canonical(o) for d in documents for o in _objects(d) if _is_record(o)}
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            problems.append(f"{name}: not JSON ({error}), so it cannot be read")
    if name.endswith(".csv"):
        problems += _csv_score_problems(name, data)
    # What the release refuses, written out in any text the file holds: a page's source as well as what it shows
    # (whole-branch review, reviewer B), a string inside JSON, base64, a CSV cell, a PDF's text, any case (`correct`:
    # tests/forms.py): a held key, a held task's graded run record, a combined score (reviewers A and B, slice 17
    # round 1, S3 and H1).
    views = _text_views(name, data)
    embedded = [o for x in views for v in _embedded_json(x.casefold()) for o in _objects(v)]
    if not any("answer key" in p for p in problems) and any(_canonical(o) in held.answers for o in embedded):
        problems.append(f"{name}: holds a held task's answer key or a tax answer sheet in its text")
    if any(
        _is_record(o) and _canonical(o) not in structured and str(o["task_id"]).upper() in held.tasks and _graded(o)
        for o in embedded
    ):
        problems.append(f"{name}: holds a held task's graded run record in its text")
    # A score is a field named for one in any JSON the text holds, however it is spaced (reviewer B, slice 17 round 2,
    # D4), or a number written beside the words.
    scored = any(_SCORE_KEY.fullmatch(k) for o in embedded for k, _ in _walk(o)) or any(
        _SCORE_SHOWN.search(" ".join(x.split())) for x in views
    )
    if scored and not any("combined score" in p for p in problems):
        problems.append(f"{name}: shows a combined score")
    if _is_stamped_pdf(name, data):
        problems += [name + p for p in _stamp_problems(data, held.marks_of(name))]
    home = _HOME.search(views[0])
    if home:
        problems.append(f"{name}: a home-folder path ({home.group(0)!r})")
    return problems


# The notice (choice 2).


def _is_book_json(relative: str) -> bool:
    """A JSON file of the book, by where it sits relative to the root it ships in."""
    path = PurePosixPath(relative)
    return path.name in BOOK_FILES or bool(BOOK_FOLDERS & set(path.parts[:-1]))


def _notice_problem(
    name: str, relative: str, data: bytes, covered: Callable[[], bool], notice: str = NOTICE
) -> str | None:
    """`relative`: the file's path from the root it ships in (the bundle, or its zip); `covered`: whether a
    metadata.json or NOTICE.txt carrying the notice sits at the root of the folder it ships in; `notice`: the notice
    this file carries, the reviewed notice on a reviewed tax task's key or page (`HeldMaterial.notice_of`)."""
    if name.endswith(".pdf"):
        if _is_stamped_pdf(name, data):
            return None  # stamped_problems names each page of a return or a form without the notice
        bare = [n for n, t in enumerate(pdf_pages_text(data), 1) if not (contains_notice(t) or _has_footer(t))]
        return f"{name}: page {', '.join(map(str, bare))} without the notice" if bare else None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    if name.endswith(".html"):
        shown = contains_notice(html_visible_text(text), notice)
    elif name.endswith((".md", ".txt")):
        shown = contains_notice(text)
    elif name.endswith(".jsonl"):
        shown = contains_notice(next(iter(text.splitlines()), ""))
    elif name.endswith(".json"):
        try:
            document = json.loads(text)
        except json.JSONDecodeError:
            return None  # named by _file_problems
        own = isinstance(document, dict) and document.get("notice") == notice  # pyright: ignore[reportUnknownMemberType]
        shown = own or (_is_book_json(relative) and covered())
        if not shown and not _is_book_json(relative):
            return f"{name}: no top-level notice"
    else:
        shown = contains_notice(text) or covered()
    return None if shown else f"{name}: no notice, and no {METADATA} or {NOTICE_FILE} with it where it ships"


def _has_footer(text: str) -> bool:
    return all(line in text for line in FOOTER_LINES)


def _notice_problems(tree: Path, names: list[str], roots: list[str], held: HeldMaterial) -> list[str]:
    @cache
    def has_notice_file(folder: str) -> bool:
        notice = tree / folder / NOTICE_FILE
        return notice.is_file() and contains_notice(notice.read_text(encoding="utf-8", errors="ignore"))

    @cache
    def covers(folder: str) -> bool:
        metadata = tree / folder / METADATA
        if has_notice_file(folder):
            return True
        try:
            return json.loads(metadata.read_text(encoding="utf-8")).get("notice") == NOTICE
        except (OSError, ValueError, AttributeError):
            return False

    def covered(name: str) -> Callable[[], bool]:
        # The folders it ships in, up to its zip's root; the bundle's own root covers only the files beside it.
        root, parent = _root_of(name, roots), posixpath.dirname(name)
        folders: list[str] = []
        folder = parent
        while folder not in (root, ""):
            folders.append(folder)
            folder = posixpath.dirname(folder)
        if root or not parent:
            folders.append(root)
        return lambda: any(covers(f) for f in folders)

    problems = [
        f"{_shown(r).removesuffix(ZIP_MARK)}: no {NOTICE_FILE} with the notice at its root"
        for r in roots
        if not has_notice_file(r)
    ]
    for name in names:
        root = _root_of(name, roots)
        relative = name[len(root) + 1 :] if root else name
        shown = _shown(name)
        found = _notice_problem(shown, relative, (tree / name).read_bytes(), covered(name), held.notice_of(shown))
        problems += [found] if found else []
    return problems


# The bundle's parts.


# The layout (reviewers A and B, slice 16 round 1: anything copied into a published folder shipped).


@dataclass(frozen=True)
class _Layout:
    """What the layout is read against: the bundle, its book's manifest (None if it cannot be read: named by
    _household_problems), its featured households and the held material."""

    bundle: Path
    manifest: Manifest | None
    featured: frozenset[str]
    held: HeldMaterial

    def same(self, name: str, other: str) -> bool:
        """Whether the bundle's file `name` has the bytes of its file `other`."""
        twin = self.bundle / other
        return twin.is_file() and twin.read_bytes() == (self.bundle / name).read_bytes()


def _featured(bundle: Path) -> frozenset[str]:
    try:
        households = json.loads((bundle / BOOK / SEALED_HOUSEHOLDS).read_text(encoding="utf-8"))["households"]
        return frozenset(str(h["household_id"]) for h in households if h.get("set") == FEATURED)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return frozenset()


def _book_problems(layout: _Layout, files: list[str]) -> list[str]:
    """`book/` is exactly the files its manifest lists, less the tax summaries, and the manifest, each with the
    bytes the manifest lists for it (reviewer B, slice 16 round 1: a sealed file changed under an old manifest)."""
    if layout.manifest is None:
        return []
    listed = {n: d for n, d in layout.manifest.files.items() if not is_tax_summary(n)}
    problems: list[str] = []
    shipped = {name.removeprefix(f"{BOOK}/") for name in files if name.startswith(f"{BOOK}/")}
    for own in sorted(shipped - {MANIFEST}):
        name = f"{BOOK}/{own}"
        if own not in listed:
            problems.append(f"{name}: not a file the release's book ships (its manifest's, less the tax summaries)")
        elif listed[own] != _digest((layout.bundle / name).read_bytes()):
            problems.append(f"{name}: not the bytes the book's manifest lists for {own}")
    problems += [f"{BOOK}/{own}: listed in the book's manifest, but missing" for own in sorted(listed.keys() - shipped)]
    return problems


def _pdf_problem(name: str, own: str) -> str | None:
    """`own`: the PDF's path in the book (or the packet). A PDF ships only as a household's document or a sealed
    return; any other is refused (reviewer B, slice 16 round 1: a flattened return copied into audit/)."""
    if not name.endswith(".pdf") or _BOOK_PDF.fullmatch(own):
        return None
    return f"{name}: a PDF outside the book's {DOCUMENTS}/ and sealed {RETURNS}/"


def _site_problem(layout: _Layout, name: str) -> str | None:
    own = name.removeprefix(f"{SITE}/")
    data = f"{data_root(layout.manifest.version)}/" if layout.manifest is not None else None
    if data is not None and own.startswith(data):
        book = f"{BOOK}/{own.removeprefix(data)}"
        return _pdf_problem(name, own.removeprefix(data)) or (
            None if layout.same(name, book) else f"{name}: not the release's {book}"
        )
    if own.startswith(f"{SITE_RUNS}/"):
        runs = f"{RUNS}/{own.removeprefix(f'{SITE_RUNS}/')}"
        return None if layout.same(name, runs) else f"{name}: not the release's {runs}"
    if own.startswith(f"{PACKETS}/"):
        return None if layout.same(name, own) else f"{name}: not the release's {own}"
    if own == NOTICE_FILE or own.startswith("static/") or _SITE_PAGE.fullmatch(own):
        return _pdf_problem(name, "")
    return _pdf_problem(name, "") or f"{name}: not a file the release puts in {SITE}/"


def _packet_problems(layout: _Layout, name: str) -> list[str]:
    """A case packet: named for a featured household, holding its source sets, the shared securities files and
    metadata as the release's book has them, its notice and its answer sheet, and nothing else."""
    found = _PACKET_ZIP.fullmatch(name.removeprefix(f"{PACKETS}/"))
    if found is None or found["household"] not in layout.featured:
        return [f"{name}: not a featured household's case packet"]
    try:
        members = read_zip((layout.bundle / name).read_bytes())
    except ZipError:
        return []  # named by the scan tree
    prefix = f"{HOUSEHOLDS}/{found['household']}/"
    problems: list[str] = []
    for member in sorted(members):
        shown, parts = f"{name}{ZIP_MARK}{member}", member.split("/")
        sourced = member.startswith(prefix) and len(parts) > 3 and parts[2] in SOURCE_SETS
        if not (sourced or member in PACKET_FILES):
            problems.append(f"{shown}: not a file a case packet holds")
        elif member == TAX_ANSWER_SHEET:
            # Only the packet's own household's sheet, as the book has it, once a review statement covers its return.
            sheet = layout.held.tax_sheets.get(found["household"])
            try:
                same = sheet is not None and _canonical(json.loads(members[member])) == sheet
            except (UnicodeDecodeError, json.JSONDecodeError):
                same = False
            if not same:
                problems.append(f"{shown}: not the tax answer sheet of {found['household']} a review statement covers")
        elif problem := _pdf_problem(shown, member):
            problems.append(problem)
        elif member not in (NOTICE_FILE, "answer-sheet.json", TAX_ANSWER_SHEET):
            twin = layout.bundle / BOOK / member
            if not (twin.is_file() and twin.read_bytes() == members[member]):
                problems.append(f"{shown}: not the release's {BOOK}/{member}")
    return problems


def _place_problems(layout: _Layout, name: str) -> list[str]:
    """One file of the bundle, outside `book/` and `runs/` (read whole by _book_problems and run_layout_problems)."""
    path = PurePosixPath(name)
    top = path.parts[0]
    if len(path.parts) == 1:
        return [] if name in TOP_FILES else [f"{name}: not a file the release puts at its root"]
    if name in FIXED_FILES:
        return []
    if top == SITE:
        problem = _site_problem(layout, name)
        return [problem] if problem else []
    if top == PACKETS:
        return _packet_problems(layout, name)
    if top == KEYS:
        if path.suffix == ".json" and path.stem in layout.held.tasks and len(path.parts) == 2:
            return [f"{name}: the key of held task {path.stem}"]
        if path.suffix == ".json" and path.stem in layout.held.open_tasks and len(path.parts) == 2:
            return []
        return [f"{name}: not the key of a public task that is not held"]
    if name.startswith(f"{IMAGES}/") and len(path.parts) == 3:
        if path.suffix == ".svg":
            return []
        if path.suffix == ".png" and _is_committed_image(name, (layout.bundle / name).read_bytes(), layout.held):
            return []
        if path.suffix == ".png":
            return [f"{name}: not the committed {IMAGES}/{path.name}"]
    return [_pdf_problem(name, "") or f"{name}: not a file the release puts there"]


def _is_committed_image(name: str, data: bytes, held: HeldMaterial) -> bool:
    """A PNG the gate cannot read ships only as one of the README's committed screenshots of the gated site
    (tools/readme_images.py), at its place and with its bytes."""
    path = PurePosixPath(name)
    return str(path.parent) == IMAGES and path.suffix == ".png" and held.images.get(path.name) == _digest(data)


def layout_problems(bundle: Path, held: HeldMaterial) -> list[str]:
    """Every file of the bundle that is not one the release puts where it sits, named; members of the case packets
    included. The layout is `_stage`'s in release.py."""
    files = sorted(p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file())
    try:
        manifest: Manifest | None = read_manifest(bundle / BOOK)
    except FileFormatError:
        manifest = None
    layout = _Layout(bundle, manifest, _featured(bundle), held)
    problems = _book_problems(layout, files)
    problems += [
        p
        for name in files
        if name.startswith(f"{BOOK}/") and name != f"{BOOK}/{MANIFEST}"
        for p in [_pdf_problem(name, name.removeprefix(f"{BOOK}/"))]
        if p
    ]
    if (bundle / RUNS).is_dir():
        try:
            problems += [f"{RUNS}/{p}" for p in run_layout_problems(bundle / RUNS)]
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as error:
            problems.append(f"{RUNS}/: a run's file cannot be read ({error})")
    for name in files:
        if not name.startswith((f"{BOOK}/", f"{RUNS}/")):
            problems += _place_problems(layout, name)
    return problems


def _household_problems(bundle: Path, names: list[str]) -> list[str]:
    """Every household the book's checks fail, and every household folder anywhere in the bundle that its manifest
    does not list. That each file is the checked book's is the layout's to say (layout_problems)."""
    try:
        manifest: Manifest = read_manifest(bundle / BOOK)
    except FileFormatError as error:
        return [f"{BOOK}/{error}, so no household can be checked"]
    report = check_book(bundle / BOOK)
    failed = sorted(report.failed_households())
    problems = [f"{BOOK}/{HOUSEHOLDS}/{h}: fails its checks" for h in failed]
    listed = {h.household_id for h in manifest.households}
    unlisted: set[str] = set()
    for name in names:
        parts = PurePosixPath(name).parts
        if HOUSEHOLDS not in parts[:-2]:
            continue
        at = parts.index(HOUSEHOLDS)
        if parts[at + 1] not in listed:
            unlisted.add("/".join(parts[: at + 2]))
    problems += [f"{_shown(f)}: a household the book's manifest does not list" for f in sorted(unlisted)]
    return problems


def _run_folders(bundle: Path) -> list[tuple[str, Path]]:
    return [(where, bundle / where) for where in (RUNS, f"{SITE}/{SITE_RUNS}") if (bundle / where).is_dir()]


def _result_problems(bundle: Path) -> list[str]:
    """Every published result names its tool, version, model and date; the private set's counts are only counts;
    no run record ran on real tickers without the mapper."""
    problems: list[str] = []
    for where, runs in _run_folders(bundle):
        for path in sorted(runs.rglob("*.json")):
            try:
                require_named(json.loads(path.read_text(encoding="utf-8")), f"{where}/{path.relative_to(runs)}")
            except UnnamedResultError as error:
                problems.append(str(error))
            except (UnicodeDecodeError, ValueError, AttributeError):
                continue  # not a record: named by _file_problems and the layout
        problems += [f"{where}/{p}" for p in unmapped_record_problems(runs)]
    for path in sorted((bundle / RESULTS).rglob("*.json")):
        name = path.relative_to(bundle).as_posix()
        problems += [f"{name}: {p}" for p in private_outcomes_problems(path.read_text(encoding="utf-8"))]
    return problems


def _verdict_problems(bundle: Path, held: HeldMaterial) -> list[str]:
    problems = [f"{SITE}/{p}" for p in held_page_problems(bundle / SITE, held.tasks)]
    if (bundle / RUNS).is_dir():
        problems += held_page_problems(bundle, held.tasks, runs=bundle / RUNS)
    return problems


def release_problems(bundle: Path, held: HeldMaterial) -> list[str]:
    """Everything in the release bundle that keeps it from shipping, one line each, naming the file."""
    with tempfile.TemporaryDirectory() as scratch:
        tree = Path(scratch) / "bundle"
        tree.mkdir()
        roots, problems = _scan_tree(bundle, tree)
        names = sorted(p.relative_to(tree).as_posix() for p in tree.rglob("*") if p.is_file())
        for name in names:
            in_zip = bool(_root_of(name, roots))
            problems += _file_problems(_shown(name), (tree / name).read_bytes(), held, in_zip)
        problems += _notice_problems(tree, names, roots, held)
        problems += layout_problems(bundle, held)
        problems += _verdict_problems(bundle, held)
        problems += _household_problems(bundle, names)
        problems += _result_problems(bundle)
        # The README's committed screenshots are known by their bytes; no gate can read a PNG's text.
        for name in (n for n in names if n.startswith(f"{IMAGES}/") and n.endswith(".png")):
            if _is_committed_image(name, (tree / name).read_bytes(), held):
                (tree / name).unlink()
        for gate in (real_identifier_problems, synthetic_problems, private_set_problems):
            try:
                problems += [_shown(p) for p in gate(tree)]
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                problems.append(f"{gate.__name__} cannot read the bundle ({error})")
    return problems
