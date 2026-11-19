"""`casebook sample-book`: the sample book, the 20 featured households as the plugin ships them (docs/SPEC.md,
Words), written from a checked default book into `plugin/book/` and gated before it replaces what is there.

It holds each featured household's four source sets, the securities and their synthetic prices, the book's
metadata under the sample book's title, the notice, and a manifest of its own: no sealed file of any kind and
no background household."""

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from casebook.checks import check_book
from casebook.model.archetypes import HELD_OUT_ARCHETYPES, frozen
from casebook.model.files import (
    ALIASES,
    MANIFEST,
    METADATA,
    PRICES_CSV,
    SEALED_HOUSEHOLDS,
    SECURITIES_CSV,
    SOURCE_SETS,
    TAX_SUMMARY,
    FileFormatError,
    household_dir,
    json_text,
    read_json,
)
from casebook.notice import NOTICE
from casebook.publish.gates import real_identifier_problems, synthetic_problems
from casebook.publish.private_set import private_set_problems
from casebook.site import FEATURED

TITLE = "The Indus Casebook: sample book"
NOTICE_FILE = "NOTICE.txt"
HOUSEHOLDS = "households"
SEALED = "sealed"


class SampleBookError(RuntimeError):
    pass


@dataclass(frozen=True)
class SampleBook:
    households: tuple[str, ...]
    files: int


def notice_text() -> str:
    return NOTICE + "\n"


def _featured(book: Path) -> list[dict[str, Any]]:
    return [h for h in read_json(book, SEALED_HOUSEHOLDS)["households"] if h["set"] == FEATURED]


def build_sample_book(book: Path, out: Path) -> SampleBook:
    """Write the sample book from `book` into `out`, through a staging folder beside it that is gated first."""
    if read_json(book, METADATA).get("securities") != ALIASES:
        raise SampleBookError(f"{book} is not a default build; the plugin shows securities under aliases only")
    featured = _featured(book)
    held = sorted(h["household_id"] for h in featured if h["archetype"] in HELD_OUT_ARCHETYPES)
    if held and not frozen():
        raise SampleBookError(f"{', '.join(held)}: held out until the freeze, so not in the sample book")
    report = check_book(book)
    if not report.passed:
        failed = ", ".join(sorted(report.failed_households()))
        raise SampleBookError(f"households failed their checks and cannot be packaged: {failed}")
    ids = {h["household_id"] for h in featured}
    manifest = read_json(book, MANIFEST)
    book_files: dict[str, str] = manifest["files"]
    copied = [SECURITIES_CSV, PRICES_CSV]
    copied += [n for n in book_files if PurePosixPath(n).parts[:2] in {(HOUSEHOLDS, i) for i in ids}]
    written = {
        METADATA: json_text({**read_json(book, METADATA), "title": TITLE}).encode(),
        NOTICE_FILE: notice_text().encode(),
    }
    staging = out.with_name(out.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    for name in copied:
        target = staging / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(book / name, target)
    for name, data in written.items():
        (staging / name).write_bytes(data)
    # The copied files' hashes are the book's own, so a book file changed after its build fails the gate.
    hashes = {name: book_files[name] for name in copied} | {
        name: hashlib.sha256(data).hexdigest() for name, data in written.items()
    }
    households = [h for h in manifest["households"] if h["household_id"] in ids]
    sample = {
        "version": manifest["version"],
        "seed": manifest["seed"],
        "households": households,
        "files": dict(sorted(hashes.items())),
    }
    (staging / MANIFEST).write_text(json_text(sample), encoding="utf-8")
    problems = sample_book_problems(staging, len(featured))
    if problems:
        shutil.rmtree(staging)
        raise SampleBookError("the sample book fails its gates:\n  " + "\n  ".join(problems))
    if out.exists():
        shutil.rmtree(out)
    staging.rename(out)
    return SampleBook(tuple(h["household_id"] for h in households), len(hashes) + 1)


def _allowed(name: str, households: set[str]) -> bool:
    parts = PurePosixPath(name).parts
    if name in (METADATA, NOTICE_FILE, SECURITIES_CSV, PRICES_CSV):
        return True
    return len(parts) > 3 and parts[0] == HOUSEHOLDS and parts[1] in households and parts[2] in SOURCE_SETS


def sample_book_problems(folder: Path, featured: int) -> list[str]:
    """What keeps a finished sample book from shipping: a price without the synthetic label, a real identifier,
    anything of the private set, a sealed or tax-summary file, a household or file its manifest does not list, a
    file whose hash is not its manifest's, a household count other than the book's `featured`, or no notice."""
    problems = synthetic_problems(folder) + real_identifier_problems(folder) + private_set_problems(folder)
    on_disk = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
    for name in on_disk:
        if PurePosixPath(name).parts[0] == SEALED or PurePosixPath(name).name == TAX_SUMMARY:
            problems.append(f"{name}: a sealed file, which the sample book never holds")
    try:
        manifest = read_json(folder, MANIFEST)
        listed = {str(h["household_id"]) for h in manifest["households"]}
        files: dict[str, str] = manifest["files"]
    except (FileFormatError, KeyError, TypeError) as error:
        return [*problems, f"{MANIFEST} is missing or malformed ({error})"]
    if len(manifest["households"]) != featured:
        problems.append(f"{MANIFEST} lists {len(manifest['households'])} households; the book has {featured} featured")
    folders = (
        {p.name for p in (folder / HOUSEHOLDS).iterdir() if p.is_dir()} if (folder / HOUSEHOLDS).is_dir() else set()
    )
    problems += [f"{household_dir(h)}: a household not in the sample book's manifest" for h in sorted(folders - listed)]
    problems += [f"{household_dir(h)}: listed in the manifest with no files" for h in sorted(listed - folders)]
    for name in on_disk:
        if name == MANIFEST:
            continue
        if name not in files:
            problems.append(f"{name}: not in the manifest's files")
        elif hashlib.sha256((folder / name).read_bytes()).hexdigest() != files[name]:
            problems.append(f"{name}: its hash is not the one the manifest gives")
    problems += [f"{name}: in the manifest's files but missing" for name in sorted(files.keys() - set(on_disk))]
    problems += [f"{name}: not a file the sample book holds" for name in sorted(files) if not _allowed(name, listed)]
    try:
        if read_json(folder, METADATA).get("notice") != NOTICE:
            problems.append(f"{METADATA} lacks the notice")
    except FileFormatError:
        problems.append(f"{METADATA} is missing or unreadable, so it lacks the notice")
    notice = folder / NOTICE_FILE
    if not notice.is_file() or notice.read_text(encoding="utf-8") != notice_text():
        problems.append(f"{NOTICE_FILE} is not the notice")
    return problems
