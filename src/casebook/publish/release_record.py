"""The stable-ID record (docs/SPEC.md, Rules: "Stable IDs: a published household or task ID never changes meaning.
Corrections ship as a new version with an errata entry").

Each release tag's entry in `published/releases.json` records, for every household and task ID it ships, a digest
of what the ID means: a household's manifest entries (path and hash) under `households/<id>/` and `sealed/<id>/`,
with its own entries in the book's shared sealed files (its planted items in the registry, its line in the sealed
household list); a task's file bytes and its grader's hash. Before a tag is recorded, today's digests are held
against every release before it (docs/PLAN.md, the household's state table: a correction goes back to `generated`
under a new version, refused when "the same version is reused, or no errata entry exists").
"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from casebook.graders.registry import GRADERS
from casebook.model.files import MANIFEST, REGISTRY, SEALED_HOUSEHOLDS, json_text, read_json
from casebook.model.ledger import IdLedger
from casebook.notice import NOTICE
from casebook.site.errata import Correction
from casebook.tasks.task import load_task

RELEASES = Path(__file__).resolve().parents[3] / "published" / "releases.json"
RELEASE_FIELDS = ("tag", "book_version", "date", "ids")
KINDS = ("households", "tasks")
TAG = re.compile(r"v\d+\.\d+\.\d+")
VERSION = re.compile(r"\d+(?:\.\d+)*")
SHA256 = re.compile(r"[0-9a-f]{64}")

Digests = dict[str, dict[str, str]]


class ReleaseRecordError(ValueError):
    pass


@dataclass(frozen=True)
class Release:
    tag: str
    book_version: str
    date: date
    ids: Digests

    def to_dict(self) -> dict[str, Any]:
        return {"tag": self.tag, "book_version": self.book_version, "date": self.date.isoformat(), "ids": self.ids}


def id_digests(book: Path, tasks: Path, keys: Path | None = None) -> Digests:
    """What each household of the book (its version folder) and each task file in `tasks` means, as a sha256.
    `keys`: the published keys (`published/keys`); a task's published key is part of what it means, so a key
    changed under the same book version changes the task's digest (reviewer A, slice 16 round 1, S3)."""
    manifest = json.loads((book / MANIFEST).read_text(encoding="utf-8"))
    files: dict[str, str] = manifest["files"]
    registry: list[dict[str, Any]] = read_json(book, REGISTRY)["entries"]
    sealed = {str(h["household_id"]): h for h in read_json(book, SEALED_HOUSEHOLDS)["households"]}
    households: dict[str, str] = {}
    for household in sorted(str(h["household_id"]) for h in manifest["households"]):
        prefixes = (f"households/{household}/", f"sealed/{household}/")
        digest = hashlib.sha256()
        for path in sorted(p for p in files if p.startswith(prefixes)):
            digest.update(f"{path}\0{files[path]}\n".encode())
        # A household's meaning includes its planted items and its archetype, set, role and twin kind, which live
        # in files the whole book shares; only its own entries in them count, so another household's change
        # leaves its digest alone.
        items = sorted((e for e in registry if e["household_id"] == household), key=lambda e: str(e["item_id"]))
        digest.update(f"{REGISTRY}\0{_canonical(items)}\n".encode())
        digest.update(f"{SEALED_HOUSEHOLDS}\0{_canonical(sealed.get(household))}\n".encode())
        households[household] = digest.hexdigest()
    task_digests: dict[str, str] = {}
    for path in sorted(tasks.glob("*.toml")):
        task = load_task(path)
        if task.task_id in task_digests:
            raise ReleaseRecordError(f"{path.name}: task {task.task_id} is in two files")
        if task.grader not in GRADERS:
            raise ReleaseRecordError(f"{path.name}: grader {task.grader!r} is not registered")
        # The task's own sha256 is of its file's bytes (tasks.task.load_task).
        lines = f"task\0{task.sha256}\ngrader\0{GRADERS[task.grader].sha256()}\n"
        key = keys / manifest["version"] / f"{task.task_id}.json" if keys is not None else None
        if key is not None and key.is_file():
            lines += f"key\0{hashlib.sha256(key.read_bytes()).hexdigest()}\n"
        task_digests[task.task_id] = hashlib.sha256(lines.encode()).hexdigest()
    return {"households": households, "tasks": task_digests}


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _version(text: str) -> tuple[int, ...]:
    if not VERSION.fullmatch(text):
        raise ReleaseRecordError(f"{text!r} is not a version (numbers and dots)")
    return tuple(int(p) for p in text.split("."))


def _digests(raw: Any, where: str) -> Digests:
    if not isinstance(raw, dict) or sorted(raw) != sorted(KINDS):  # pyright: ignore[reportUnknownArgumentType]
        raise ReleaseRecordError(f'{where}: ids are {{"households": {{...}}, "tasks": {{...}}}}')
    out: Digests = {}
    for kind in KINDS:
        entries: Any = raw[kind]
        if not isinstance(entries, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and SHA256.fullmatch(v)
            for k, v in entries.items()  # pyright: ignore[reportUnknownVariableType]
        ):
            raise ReleaseRecordError(f"{where}: {kind} map each ID to a sha256")
        out[kind] = dict(entries)  # pyright: ignore[reportUnknownArgumentType]
    return out


def _release(raw: Any, where: str) -> Release:
    if not isinstance(raw, dict) or sorted(raw) != sorted(RELEASE_FIELDS):  # pyright: ignore[reportUnknownArgumentType]
        raise ReleaseRecordError(f"{where}: a release has exactly {', '.join(RELEASE_FIELDS)}")
    entry: dict[str, Any] = raw  # pyright: ignore[reportUnknownVariableType]
    tag, book_version = str(entry["tag"]), str(entry["book_version"])
    if not TAG.fullmatch(tag):
        raise ReleaseRecordError(f"{where}: {tag!r} is not a release tag (v and three numbers)")
    _version(book_version)
    try:
        day = date.fromisoformat(str(entry["date"]))
    except ValueError as error:
        raise ReleaseRecordError(f"{where}: {entry['date']!r} is not a date (YYYY-MM-DD)") from error
    return Release(tag, book_version, day, _digests(entry["ids"], where))


def load_releases(path: Path = RELEASES) -> list[Release]:
    """The recorded releases, oldest first. The record carries the notice (the owner's decision of 19 November
    2026, choice 2: JSON the release copies from `published/` has a `notice` field)."""
    if not path.is_file():
        raise ReleaseRecordError(f"{path} is not a file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ReleaseRecordError(f"{path.name} is not JSON: {error}") from error
    if not isinstance(data, dict) or sorted(data) != ["notice", "releases"]:  # pyright: ignore[reportUnknownArgumentType]
        raise ReleaseRecordError(f'{path.name}: the record is {{"notice": ..., "releases": [...]}}')
    record: dict[str, Any] = data  # pyright: ignore[reportUnknownVariableType]
    if record["notice"] != NOTICE:
        raise ReleaseRecordError(f"{path.name}: its notice is not the notice")
    if not isinstance(record["releases"], list):
        raise ReleaseRecordError(f"{path.name}: releases is a list")
    entries: list[Any] = record["releases"]  # pyright: ignore[reportUnknownVariableType]
    releases = [_release(e, f"{path.name} release {i + 1}") for i, e in enumerate(entries)]
    tags = [r.tag for r in releases]
    if len(set(tags)) != len(tags):
        raise ReleaseRecordError(f"{path.name}: a tag is recorded twice")
    versions = [_version(r.book_version) for r in releases]
    if versions != sorted(versions):
        raise ReleaseRecordError(f"{path.name}: book versions go back in time")
    return releases


def stable_id_problems(
    current: Digests, book_version: str, releases: list[Release], errata: list[Correction], ledger: IdLedger
) -> list[str]:
    """Why today's IDs may not ship as book `book_version` after `releases` (oldest first); none when they may.

    At the last release's book version, every ID means what it meant then and none is added. At a newer one, an
    ID whose digest changed is named by an errata entry for a version after the last release's, up to this one.
    No released ID goes missing, every ID is in the ID ledger, and the book's version never goes back."""
    problems: list[str] = []
    ledgered = {"households": set(ledger.households), "tasks": set(ledger.tasks)}
    for kind in KINDS:
        problems += [f"{i} is not in the ID ledger" for i in sorted(set(current[kind]) - ledgered[kind])]
        released = {i for r in releases for i in r.ids[kind]}
        problems += [f"{i} was released and is missing" for i in sorted(released - set(current[kind]))]
    if not releases:
        return problems
    last = releases[-1]
    now, then = _version(book_version), _version(last.book_version)
    if now < then:
        return [*problems, f"book version {book_version} is older than {last.tag}'s, {last.book_version}"]
    if now == then:
        for kind in KINDS:
            for i in sorted(current[kind]):
                if i not in last.ids[kind]:
                    problems.append(f"{i} is new under book version {book_version}, which {last.tag} released")
                elif current[kind][i] != last.ids[kind][i]:
                    problems.append(
                        f"{i} changed under book version {book_version}, which {last.tag} released: "
                        "a correction ships as a new book version with an errata entry"
                    )
        return problems
    named: set[str] = set()
    for correction in errata:
        try:
            if then < _version(correction.version) <= now:
                named |= set(correction.ids)
        except ReleaseRecordError as error:
            problems.append(f"the errata log's entry for {correction.version!r}: {error}")
    for kind in KINDS:
        for i in sorted(set(current[kind]) & set(last.ids[kind])):
            if current[kind][i] != last.ids[kind][i] and i not in named:
                problems.append(
                    f"{i} changed since {last.tag} (book {last.book_version}) and no errata entry for a version "
                    f"after {last.book_version}, up to {book_version}, names it"
                )
    return problems


def record_release(
    tag: str,
    book_version: str,
    day: date,
    current: Digests,
    errata: list[Correction],
    ledger: IdLedger,
    path: Path = RELEASES,
) -> Release:
    """Add `tag`'s entry to the record, unless its IDs fail the stable-ID rule against the releases before it. A
    tag already recorded with the same book version and digests is left as it is; with others, it is refused."""
    if not TAG.fullmatch(tag):
        raise ReleaseRecordError(f"{tag!r} is not a release tag (v and three numbers)")
    releases = load_releases(path)
    recorded = next((r for r in releases if r.tag == tag), None)
    if recorded is not None:
        if recorded.book_version != book_version or recorded.ids != current:
            raise ReleaseRecordError(
                f"{tag} is already recorded with other digests or another book version: a recorded tag never "
                "changes; a correction ships as a new book version under a new tag"
            )
        return recorded
    problems = stable_id_problems(current, book_version, releases, errata, ledger)
    if problems:
        raise ReleaseRecordError(f"{tag} cannot be recorded:\n" + "\n".join(problems))
    release = Release(tag, book_version, day, {kind: dict(sorted(current[kind].items())) for kind in KINDS})
    record = {"notice": NOTICE, "releases": [r.to_dict() for r in [*releases, release]]}
    path.write_text(json_text(record), encoding="utf-8")
    return release
