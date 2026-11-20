"""The preview release's gates: what `casebook release --preview` refuses to ship (docs/PLAN.md, slice 16).

A release bundle fails on: a tax or RMD answer key, a tax answer sheet or a verdict on a tax-lot or RMD task; a
combined score; a household with a failed check; a real ticker or security name; a private task, fixture or key; a
filled-form page with no watermark; a file with no notice; a result with no tool, version, model or date; anything
from `out/real/`; and a home-folder path (the owner's decision of 19 November 2026,
docs/decisions/2026-11-19-slice16-release-choices.md, choices 2 and 5a).

The gate tells held material from what may ship by where it comes from (docs/PLAN.md, "What stays held for tax and
RMD"): a held task's key from `out/keys/` and a household's tax summary are refused by their bytes, and by their
content wherever it is copied into a JSON document; the registry's justified conclusions are not.

Every file of the bundle is read, and every member of every zip in it. The bundle is read through a scan tree, a
folder of links to its files in which each zip is unpacked into a folder named for it with a `!`, so the gates that
read a folder read the members too, and a member is named as `packets/HH-4821.zip!households/...`.
"""

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
from casebook.model.files import (
    ALIASES,
    MANIFEST,
    METADATA,
    TAX_SUMMARY,
    FileFormatError,
    Manifest,
    is_tax_summary,
    read_manifest,
)
from casebook.notice import NOTICE, contains_notice
from casebook.publish.gates import (
    held_page_problems,
    real_identifier_problems,
    synthetic_problems,
    unmapped_record_problems,
)
from casebook.publish.private_set import private_set_problems
from casebook.publish.zips import ZipError, read_zip
from casebook.published_text import UnscannableFileError, html_visible_text, pdf_pages_text, text_of
from casebook.site.results import private_outcomes_problems
from casebook.site.tasks import UnnamedResultError, is_held, require_named
from casebook.sources.pdf import FOOTER_SIZE, MARGIN
from casebook.tasks.task import load_task
from casebook.watermark import stamped_problems

NOTICE_FILE = "NOTICE.txt"
ZIP_MARK = "!"
BOOK = "book"
SITE = "site"
RUNS = "runs"
RESULTS = "results"
KEYS = "keys"
SITE_RUNS = "data/runs"
HOUSEHOLDS = "households"
# The book's own JSON: what a build writes under these folders, and its manifest and metadata. It cannot carry the
# notice without changing book bytes, so the metadata.json or NOTICE.txt of the folder it ships in covers it.
BOOK_FOLDERS = frozenset({HOUSEHOLDS, "securities", "sealed"})
BOOK_FILES = frozenset({MANIFEST, METADATA})
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


@dataclass(frozen=True)
class HeldMaterial:
    """What the preview release never ships. `tasks`: each held task's ID and its justified conclusion. `answers`:
    the sha256 of each held key's and each tax summary's bytes, and of its content as canonical JSON less any
    notice. `real_only`: the sha256 of each file of the real-ticker build that the default build does not have."""

    tasks: dict[str, str]
    answers: frozenset[str]
    real_only: frozenset[str]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> str:
    """The digest of a parsed JSON value written canonically, a top-level notice left out: a held key copied with a
    notice added, or written with other spacing, is still the key."""
    if isinstance(value, dict):
        value = {k: v for k, v in value.items() if k != "notice"}  # pyright: ignore[reportUnknownVariableType]
    return _digest(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def _book_files(book: Path) -> dict[str, bytes]:
    return {name: (book / name).read_bytes() for name in read_manifest(book).files}


def held_material(book: Path, real_book: Path | None, tasks: Path, held_keys: Path) -> HeldMaterial:
    """`book`: the default build; `real_book`: the real-ticker build (out/real/<version>), if there is one; `tasks`:
    the public task files; `held_keys`: where `casebook run` writes held keys (out/keys), under the book's version."""
    held = {t.task_id: t.justified_conclusion for t in map(load_task, sorted(tasks.glob("T-*.toml"))) if is_held(t)}
    version = read_manifest(book).version
    keys = [held_keys / version / f"{task_id}.json" for task_id in sorted(held)]
    default = _book_files(book)
    real = _book_files(real_book) if real_book is not None else {}
    answers = [key.read_bytes() for key in keys if key.is_file()]
    answers += [data for files in (default, real) for name, data in files.items() if is_tax_summary(name)]
    digests = {_digest(a) for a in answers} | {_canonical(json.loads(a)) for a in answers}
    real_only = {_digest(d) for d in real.values()} - {_digest(d) for d in default.values()}
    return HeldMaterial(held, frozenset(digests), frozenset(real_only))


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
    """The value, if it is an object, and every object inside it."""
    if isinstance(value, dict):
        yield value
    yield from (child for _, child in _walk(value) if isinstance(child, dict))


def _graded(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    regraded: Any = record.get("regraded") or {}  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    return record.get("grade") is not None or regraded.get("grade_before") is not None  # pyright: ignore[reportUnknownMemberType]


def _json_problems(name: str, documents: list[Any], held: HeldMaterial, in_zip: bool) -> list[str]:
    problems: list[str] = []
    scores = sorted({k for d in documents for k, _ in _walk(d) if _SCORE_KEY.fullmatch(k)})
    if scores:
        problems.append(f"{name}: a combined score ({', '.join(scores)})")
    if any(_canonical(o) in held.answers for d in documents for o in _objects(d)):
        problems.append(f"{name}: holds a held task's answer key or a tax answer sheet")
    # The run records beside the site and in it are read by held_page_problems; one in a zip is read here.
    if in_zip and any(
        isinstance(d, dict) and d.get("task_id") in held.tasks and _graded(d)  # pyright: ignore[reportUnknownMemberType]
        for d in documents
    ):
        problems.append(f"{name}: a held task's run record carries its grade")
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


def _page_text(name: str, data: bytes) -> str | None:
    """The words a reader sees in a page, a Markdown file or a text file; None for any other file."""
    if name.endswith(".html"):
        return html_visible_text(data.decode("utf-8"))
    if name.endswith((".md", ".txt")):
        return data.decode("utf-8")
    return None


# A release ships each PDF in the book and again in the site's copy of it: each is read once.
@lru_cache(maxsize=1024)
def _is_filled_form(data: bytes) -> bool:
    return "/AcroForm" in PdfReader(io.BytesIO(data)).root_object


@lru_cache(maxsize=1024)
def _stamp_problems(data: bytes) -> tuple[str, ...]:
    """stamped_problems of a PDF, each line without the file's name."""
    return tuple(stamped_problems("", data))


def _file_problems(name: str, data: bytes, held: HeldMaterial, in_zip: bool) -> list[str]:
    problems: list[str] = []
    digest = _digest(data)
    if digest in held.answers:
        problems.append(f"{name}: a held task's answer key or a tax answer sheet")
    if PurePosixPath(name).name == TAX_SUMMARY:
        problems.append(f"{name}: a tax summary, a tax answer sheet held until the tax review")
    if digest in held.real_only:
        problems.append(f"{name}: a file of the real-ticker build (out/real/)")
    if name.endswith((".json", ".jsonl")):
        try:
            problems += _json_problems(name, _json_documents(name, data), held, in_zip)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            problems.append(f"{name}: not JSON ({error}), so it cannot be read")
    page = _page_text(name, data)
    if page is not None and _SCORE_SHOWN.search(" ".join(page.split())):
        problems.append(f"{name}: shows a combined score")
    if name.endswith(".pdf") and _is_filled_form(data):
        problems += [name + p for p in _stamp_problems(data)]
    home = _HOME.search(_scanned_text(name, data))
    if home:
        problems.append(f"{name}: a home-folder path ({home.group(0)!r})")
    return problems


# The notice (choice 2).


def _is_book_json(relative: str) -> bool:
    """A JSON file of the book, by where it sits relative to the root it ships in."""
    path = PurePosixPath(relative)
    return path.name in BOOK_FILES or bool(BOOK_FOLDERS & set(path.parts[:-1]))


def _notice_problem(name: str, relative: str, data: bytes, covered: Callable[[], bool]) -> str | None:
    """`relative`: the file's path from the root it ships in (the bundle, or its zip); `covered`: whether a
    metadata.json or NOTICE.txt carrying the notice sits at the root of the folder it ships in."""
    if name.endswith(".pdf"):
        if _is_filled_form(data):
            return None  # stamped_problems names each page of a filled form without the notice
        bare = [n for n, t in enumerate(pdf_pages_text(data), 1) if not (contains_notice(t) or _has_footer(t))]
        return f"{name}: page {', '.join(map(str, bare))} without the notice" if bare else None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    if name.endswith(".html"):
        shown = contains_notice(html_visible_text(text))
    elif name.endswith((".md", ".txt")):
        shown = contains_notice(text)
    elif name.endswith(".jsonl"):
        shown = contains_notice(next(iter(text.splitlines()), ""))
    elif name.endswith(".json"):
        try:
            document = json.loads(text)
        except json.JSONDecodeError:
            return None  # named by _file_problems
        own = isinstance(document, dict) and document.get("notice") == NOTICE  # pyright: ignore[reportUnknownMemberType]
        shown = own or (_is_book_json(relative) and covered())
        if not shown and not _is_book_json(relative):
            return f"{name}: no top-level notice"
    else:
        shown = contains_notice(text) or covered()
    return None if shown else f"{name}: no notice, and no {METADATA} or {NOTICE_FILE} with it where it ships"


def _has_footer(text: str) -> bool:
    return all(line in text for line in FOOTER_LINES)


def _notice_problems(tree: Path, names: list[str], roots: list[str]) -> list[str]:
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
        found = _notice_problem(_shown(name), relative, (tree / name).read_bytes(), covered(name))
        problems += [found] if found else []
    return problems


# The bundle's parts.


def _held_key_problems(names: list[str], held: HeldMaterial) -> list[str]:
    return [
        f"{_shown(n)}: the key of held task {PurePosixPath(n).stem}"
        for n in names
        if KEYS in PurePosixPath(n).parts[:-1] and PurePosixPath(n).stem in held.tasks
    ]


def _household_problems(bundle: Path, tree: Path, names: list[str]) -> list[str]:
    """Every household the book's checks fail, and every household folder anywhere in the bundle that is not one
    of the checked book's: a household its manifest does not list, or a file that is not the book's."""
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
        household, own = parts[at + 1], "/".join(parts[at:])
        if household not in listed:
            unlisted.add("/".join(parts[: at + 2]))
        elif manifest.files.get(own) != _digest((tree / name).read_bytes()):
            problems.append(f"{_shown(name)}: not the checked book's {own}")
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
        problems += _notice_problems(tree, names, roots)
        problems += _held_key_problems(names, held)
        problems += _verdict_problems(bundle, held)
        problems += _household_problems(bundle, tree, names)
        problems += _result_problems(bundle)
        for gate in (real_identifier_problems, synthetic_problems, private_set_problems):
            try:
                problems += [_shown(p) for p in gate(tree)]
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                problems.append(f"{gate.__name__} cannot read the bundle ({error})")
    return problems
