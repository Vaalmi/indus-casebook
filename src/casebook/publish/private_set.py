"""Nothing of the private set in a public file (docs/SPEC.md, Private set stays private: "the release script and
the public repo's checks fail if a private task, its fixtures or its answer key is present").

The private set lives in `$CASEBOOK_PRIVATE`. What of it could be copied into the public repo or a published
site is found three ways:

- by name: a file or folder whose path names a private task (its task file, its key, a run folder or record);
- by what it says it is: a TOML or JSON file whose `task_id`, at any depth, is a private task's (a task file, a
  key, a run record or a transcript line, under any name);
- by content: a file whose bytes, or any line of it forty characters or longer, match the private set's
  fingerprints (`book/private_fingerprints.json`: the sha256 of each private file and of each such line that no
  public file has), so a prompt or a justified conclusion pasted into another file is found too;
- by household: a file of a private pair's household (`model.archetypes.PRIVATE_PAIRS`), whose files are drawn
  only into `$CASEBOOK_PRIVATE`: its path names the household, or its top-level `household_id` (a TOML or JSON
  document's, a JSON Lines line's, a CSV row's) is the household's. So a private task's fixtures are found too,
  wherever they are copied (its CRM and portfolio files carry the household's ID). The households' IDs are not
  secret (the public ledger keeps them, with their archetype, pair and role, and a transcript of a run that
  listed the CRM's households names them); their files are.
"""

import csv
import hashlib
import io
import json
import re
import tomllib
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any

from casebook.model.archetypes import PRIVATE_PAIRS
from casebook.model.ledger import PRIVATE_TASK_ID, is_private_task_id, load_ledger

REPO = Path(__file__).resolve().parents[3]
FINGERPRINTS = REPO / "book" / "private_fingerprints.json"
LEDGER = REPO / "book" / "id_ledger.json"
_HOUSEHOLD = re.compile(r"(?<![A-Za-z0-9])HH-\d{4}(?!\d)")
HOUSEHOLD_FIELD = "household_id"
ACCOUNT_FIELD = "account_id"
# An account's number begins with its household's: SYN-12040001 is HH-1204's.
_ACCOUNT = re.compile(r"SYN-(\d{4})\d{4}")
SALT = Path("book") / "private_salt"
# A line this long is particular to its file; a shorter one ("finding = ...") is not.
LINE_LENGTH = 40
# The private set's folders whose files are fingerprinted: the task files and matrix, the keys, the tests and
# the private decision pages. Its run folders are found by name and task_id instead.
PRIVATE_FOLDERS = ("tasks", "keys", "tests", "docs")
# What the public repo holds that is not its own: tools, caches and build output. Only a scan of the repo skips
# them; a release's files are scanned whole (reviewers A and B, slice 11 round 1).
SKIPPED = frozenset({".git", ".venv", "out", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", "review"})


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lines(text: str) -> Iterator[str]:
    for line in text.splitlines():
        flat = " ".join(line.split())
        if len(flat) >= LINE_LENGTH:
            yield flat


def tree_files(root: Path, skipped: frozenset[str] = frozenset()) -> list[Path]:
    """Every file under `root`, but those under a folder `skipped` names."""
    return sorted(p for p in root.rglob("*") if p.is_file() and not skipped & set(p.relative_to(root).parts))


class SharedTextError(ValueError):
    """Private text the public repo also holds, not yet approved as shared: an accident to look at."""

    def __init__(self, overlaps: list[str]) -> None:
        super().__init__("\n".join(overlaps))
        self.overlaps = overlaps


def _where(paths: Iterable[Path], root: Path | None = None) -> tuple[dict[str, str], dict[str, str]]:
    """Each file's and each long line's digest, with the first file it is found in."""
    files: dict[str, str] = {}
    lines: dict[str, str] = {}
    for path in paths:
        name = path.relative_to(root).as_posix() if root is not None else path.as_posix()
        data = path.read_bytes()
        files.setdefault(_digest(data), name)
        for line in _lines(data.decode("utf-8", errors="ignore")):
            lines.setdefault(_digest(line.encode()), f"{name}: {line[:60]!r}")
    return files, lines


def fingerprints(
    private: Path,
    public: Path,
    fixtures: Iterable[Path] = (),
    previous: Path | None = FINGERPRINTS,
    public_builds: Sequence[Path] = (),
    approve_shared: bool = False,
) -> dict[str, list[str]]:
    """The private set's fingerprints: the sha256 of each file in its folders, of its salt and of each of its
    pairs' files (`fixtures`: their built files and each private task's fixtures, which the caller gathers),
    and of each long line of its folders' text and its salt.

    What the private set shares with public files is not fingerprinted, or every public file would be found:
    - what a public build of the book also has (`public_builds`), since public code generates it: a household's
      smallest files can be byte for byte another's (a header-only CSV);
    - what the public repo also has (the private tasks share their voice and fixed sentences with the public
      ones, and the private tests their code), but only once approved: an overlap not yet approved stops the
      regeneration with a `SharedTextError` naming each one, since it may be a private file copied out by
      accident (reviewers A and B, slice 11 round 2); `approve_shared` approves them, and the approval is kept
      in the fingerprints, where a review sees it.

    A fingerprint once taken is kept: `previous`'s are carried over, so regenerating can never clear a line or
    file already fingerprinted (reviewers A and B, slice 11 round 1)."""
    previous_data = _load(previous) if previous is not None else {}
    approved_files = set(previous_data.get("shared_files", []))
    approved_lines = set(previous_data.get("shared_lines", []))
    guards = {FINGERPRINTS.resolve(), LEDGER.resolve()}
    repo_files, repo_lines = _where([p for p in tree_files(public, SKIPPED) if p.resolve() not in guards], public)
    build_files, build_lines = _where(public_builds)
    texts = [p for folder in PRIVATE_FOLDERS if (private / folder).is_dir() for p in tree_files(private / folder)]
    texts += [private / SALT] if (private / SALT).is_file() else []
    private_files, private_lines = _where(texts, private)
    fixture_files, _ = _where(fixtures)
    candidate_files = {**fixture_files, **private_files}.keys() - build_files.keys()
    candidate_lines = private_lines.keys() - build_lines.keys()
    overlap_files = (candidate_files & repo_files.keys()) - approved_files
    overlap_lines = (candidate_lines & repo_lines.keys()) - approved_lines
    if (overlap_files or overlap_lines) and not approve_shared:
        overlaps = [
            f"{repo_files[d]} is private file {private_files.get(d, fixture_files.get(d))}"
            for d in sorted(overlap_files)
        ]
        overlaps += [f"{repo_lines[d]} is a line of {private_lines[d].split(':')[0]}" for d in sorted(overlap_lines)]
        raise SharedTextError(overlaps)
    approved_files |= overlap_files
    approved_lines |= overlap_lines
    return {
        "files": sorted(set(previous_data.get("files", [])) | (candidate_files - approved_files)),
        "lines": sorted(set(previous_data.get("lines", [])) | (candidate_lines - approved_lines)),
        "shared_files": sorted(approved_files),
        "shared_lines": sorted(approved_lines),
    }


def _load(path: Path) -> dict[str, list[str]]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def load_fingerprints(path: Path = FINGERPRINTS) -> tuple[frozenset[str], frozenset[str]]:
    data = _load(path)
    return frozenset(data.get("files", [])), frozenset(data.get("lines", []))


def private_households(ledger: Path = LEDGER) -> frozenset[str]:
    """The households of the private pairs, by the public ledger's IDs and slots."""
    if not ledger.is_file():
        return frozenset()
    return frozenset(
        household
        for household, entry in load_ledger(ledger).households.items()
        if (entry.archetype, entry.pair) in PRIVATE_PAIRS
    )


def _field(value: Any, field: str) -> Iterator[str]:
    """Every text value of `field` in a parsed TOML or JSON value, at any depth."""
    if isinstance(value, dict):
        for name, item in value.items():  # pyright: ignore[reportUnknownVariableType]
            if name == field and isinstance(item, str):
                yield item
            else:
                yield from _field(item, field)
    elif isinstance(value, list):
        for item in value:  # pyright: ignore[reportUnknownVariableType]
            yield from _field(item, field)


def _own_household(value: Any) -> Iterator[str]:
    """The household a parsed document, JSON Lines line or CSV row belongs to: its top-level `household_id`, or
    the household its top-level `account_id` belongs to (a custodian file names accounts, not households). A
    listing that names households deeper down (a book-level key, a transcript of the CRM's household list) is
    not any one household's file."""
    rows: list[Any] = value if isinstance(value, list) else [value]  # pyright: ignore[reportUnknownVariableType]
    for row in rows:
        if not isinstance(row, dict):
            continue
        household = row.get(HOUSEHOLD_FIELD)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if isinstance(household, str):
            yield household
        account = _ACCOUNT.fullmatch(str(row.get(ACCOUNT_FIELD, "")))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        if account:
            yield f"HH-{account.group(1)}"


def _parsed(path: Path, text: str) -> Iterable[Any]:
    """The file's TOML or JSON values (a JSON Lines file's, line by line); nothing for another file."""
    try:
        if path.suffix == ".toml":
            return [tomllib.loads(text)]
        if path.suffix == ".json":
            return [json.loads(text)]
        if path.suffix == ".jsonl":
            return [json.loads(line) for line in text.splitlines() if line.strip()]
        if path.suffix == ".csv":
            return [list(csv.DictReader(io.StringIO(text)))]
    except (tomllib.TOMLDecodeError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    return []


def file_problems(
    name: str, path: Path, files: frozenset[str], lines: frozenset[str], households: frozenset[str] = frozenset()
) -> list[str]:
    """What of the private set one file holds."""
    problems: list[str] = []
    named = PRIVATE_TASK_ID.search(name)
    if named:
        problems.append(f"{name}: its path names private task {named.group(0)}")
    data = path.read_bytes()
    if _digest(data) in files:
        problems.append(f"{name}: a copy of a private file")
    text = data.decode("utf-8", errors="ignore")
    parsed = list(_parsed(path, text))
    private_ids = sorted({t for value in parsed for t in _field(value, "task_id") if is_private_task_id(t)})
    if private_ids:
        problems.append(f"{name}: it is private task {', '.join(private_ids)}'s (its task_id)")
    copied = next((line for line in _lines(text) if _digest(line.encode()) in lines), None)
    if copied is not None:
        problems.append(f"{name}: a line of a private file: {copied[:60]!r}")
    in_path = set(_HOUSEHOLD.findall(name)) & households
    if in_path:
        problems.append(f"{name}: its path names private pair household {', '.join(sorted(in_path))}")
    owned = {h for value in parsed for h in _own_household(value)} & households
    if owned:
        problems.append(
            f"{name}: it is private pair household {', '.join(sorted(owned))}'s (its household or accounts)"
        )
    return problems


def private_set_problems(
    root: Path, fingerprint_file: Path = FINGERPRINTS, ledger: Path = LEDGER, repository: bool = False
) -> list[str]:
    """Every file under `root` (the public repo, or a site and its inputs about to be published) that holds
    anything of the private set. The fingerprints and the ledger, which name it to guard it, are not scanned;
    nor, in the repo (`repository`), are tools, caches and build output. A release's files are scanned whole."""
    files, lines = load_fingerprints(fingerprint_file)
    households = private_households(ledger)
    guards = {fingerprint_file.resolve(), ledger.resolve()}
    problems: list[str] = []
    for path in tree_files(root, SKIPPED if repository else frozenset()):
        if path.resolve() in guards:
            continue
        problems += file_problems(path.relative_to(root).as_posix(), path, files, lines, households)
    return problems
