"""`casebook release --preview`: the versioned bundle of the preview release (docs/PLAN.md, slice 16), built in a
staging folder from the checked default book and the committed release files, gated whole, then moved into place.

The layout and the readings behind it are the owner's choices of 19 November 2026
(docs/decisions/2026-11-19-slice16-release-choices.md): tag v<package version> ships the book under its own version;
the site carries the case packets; the review packet is never part of it."""

import hashlib
import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from importlib.metadata import version
from pathlib import Path

from casebook import BOOK_VERSION
from casebook.model.files import MANIFEST, METADATA, is_tax_summary, json_text, read_json, read_manifest
from casebook.model.ledger import load_ledger
from casebook.notice import NOTICE, NOTICE_HEADLINE
from casebook.publish.packets import PacketError, case_packets
from casebook.publish.private_set import LEDGER
from casebook.publish.release_gates import held_material, release_problems
from casebook.publish.release_record import (
    RELEASES,
    Release,
    ReleaseRecordError,
    id_digests,
    load_releases,
    record_release,
    stable_id_problems,
)
from casebook.publish.site_build import SiteBuildError, build_site
from casebook.review_statement import is_held, notice_for_task, statement_of
from casebook.site.errata import ErrataError, load_errata
from casebook.site.tasks import UnnamedResultError
from casebook.tasks.task import load_task

NOTICE_FILE = "NOTICE.txt"
RELEASE_JSON = "release.json"
AUDIT_NOTES = "AUDIT.md"
REPO_FILES = ("README.md", "LICENSE", "LICENSE-DATA")


class ReleaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseInputs:
    """What the release is built from: the repo's committed release files and the two builds."""

    book: Path
    real_book: Path | None
    repo: Path
    held_keys: Path

    @property
    def published(self) -> Path:
        return self.repo / "published"

    @property
    def tasks(self) -> Path:
        return self.repo / "tasks" / "public"


def tag() -> str:
    return f"v{version('indus-casebook')}"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _copy_tree(source: Path, target: Path) -> None:
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)


def _with_notice(source: Path, target: Path, notice: str = NOTICE) -> None:
    data = json.loads(source.read_text(encoding="utf-8"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json_text({**data, "notice": notice}), encoding="utf-8")


# The files the release takes from each published folder, and nothing else (reviewers A and B, slice 16 round 1:
# a file copied into published/audit/ shipped whatever it held). Any other file there stops the release.
AUDIT_FILES = ("audit-log.csv", AUDIT_NOTES)
RESULTS_FILES = ("private-outcomes.json",)
IMAGES = "docs/images"


def stray_problems(inputs: ReleaseInputs, recorded: Sequence[Release] = ()) -> list[str]:
    """Files in the published folders the release copies from that it would not take: each is named, so a key, a
    record or an export dropped there is seen, not silently left behind. The keys of an earlier release's book
    version stay, as that release published them, for a task that is open today (reviewer A, slice 17 round 1, D2:
    a new version, after a review statement say, left the earlier keys behind)."""
    published = inputs.published
    version = read_manifest(inputs.book).version
    versions = {version} | {r.book_version for r in recorded}
    statement = statement_of(inputs.book)
    open_tasks = {t.task_id for t in map(load_task, inputs.tasks.glob("*.toml")) if not is_held(t, statement)}
    keys = published / "keys"
    problems = [
        f"published/keys/{p.relative_to(keys).as_posix()}: not the published key of an open task"
        for p in sorted(keys.rglob("*"))
        if p.is_file()
        and not (p.parent.parent == keys and p.parent.name in versions and p.suffix == ".json" and p.stem in open_tasks)
    ]
    for folder, allowed in (("audit", AUDIT_FILES), ("results", RESULTS_FILES)):
        problems += [
            f"published/{folder}/{p.relative_to(published / folder).as_posix()}: not a file the release publishes"
            for p in sorted((published / folder).rglob("*"))
            if p.is_file() and p.relative_to(published / folder).as_posix() not in allowed
        ]
    return problems


def book_problems(book: Path) -> list[str]:
    """Every file the book's manifest lists, with the bytes it lists (reviewer B, slice 16 round 1, S6: a sealed
    file changed after the build kept every ID's digest, which trusts the manifest)."""
    manifest = read_manifest(book)
    return [
        f"{name}: its bytes are not the ones the book's manifest lists"
        for name, digest in sorted(manifest.files.items())
        if not (book / name).is_file() or _digest((book / name).read_bytes()) != digest
    ]


def _stage(inputs: ReleaseInputs, staging: Path) -> None:
    """Write every file of the bundle into `staging`."""
    published = inputs.published
    errata = published / "errata.json"
    try:
        build_site(
            inputs.book,
            staging / "site",
            inputs.repo / "README.md",
            published / "runs",
            inputs.tasks,
            published / "keys",
            errata=errata,
        )
    except (SiteBuildError, UnnamedResultError) as error:
        raise ReleaseError(f"the site cannot be built: {error}") from error
    manifest = read_manifest(inputs.book)
    for name in [*(n for n in manifest.files if not is_tax_summary(n)), MANIFEST]:
        target = staging / "book" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(inputs.book / name, target)
    try:
        packets = case_packets(inputs.book, published / "keys", inputs.tasks)
    except PacketError as error:
        raise ReleaseError(f"the case packets cannot be built: {error}") from error
    for name, data in packets.items():
        for folder in ("packets", "site/packets"):
            (staging / folder).mkdir(parents=True, exist_ok=True)
            (staging / folder / name).write_bytes(data)
    _copy_tree(published / "runs", staging / "runs")
    # The release's copies of the published keys and the freeze record carry the notice as a field (the owner's
    # choice 2); the committed files stay as the runner and `casebook freeze` wrote them.
    # A tax task's key a review statement covers carries the reviewed notice (docs/SPEC.md, Notice everywhere).
    statement = statement_of(inputs.book)
    tasks = {t.task_id: t for t in map(load_task, inputs.tasks.glob("*.toml"))}
    for key in sorted((published / "keys" / manifest.version).glob("*.json")):
        task = tasks.get(key.stem)
        _with_notice(key, staging / "keys" / key.name, NOTICE if task is None else notice_for_task(task, statement))
    _with_notice(published / "freeze.json", staging / "freeze.json")
    shutil.copyfile(published / "errata.json", staging / "errata.json")
    for folder, names in (("results", RESULTS_FILES), ("audit", AUDIT_FILES)):
        for name in names:
            (staging / folder).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(published / folder / name, staging / folder / name)
    # The README's images, so the bundle's README shows them (reviewer A, slice 16 round 1, D2).
    _copy_tree(inputs.repo / IMAGES, staging / IMAGES)
    audit = staging / "audit" / AUDIT_NOTES
    audit.write_text(f"> **{NOTICE_HEADLINE}**{NOTICE.removeprefix(NOTICE_HEADLINE)}\n\n" + audit.read_text(), "utf-8")
    for folder in ("keys", "audit", "site", IMAGES):
        (staging / folder / NOTICE_FILE).write_text(NOTICE + "\n", encoding="utf-8")
    for name in REPO_FILES:
        shutil.copyfile(inputs.repo / name, staging / name)
    (staging / NOTICE_FILE).write_text(NOTICE + "\n", encoding="utf-8")


def _release_json(staging: Path, inputs: ReleaseInputs, ids: dict[str, dict[str, str]]) -> None:
    files = {
        p.relative_to(staging).as_posix(): _digest(p.read_bytes())
        for p in sorted(staging.rglob("*"))
        if p.is_file() and p.name != RELEASE_JSON
    }
    record = {
        "notice": NOTICE,
        "tag": tag(),
        "package_version": version("indus-casebook"),
        "book_version": BOOK_VERSION,
        "seed": read_json(inputs.book, METADATA)["seed"],
        "book_manifest_sha256": _digest((inputs.book / MANIFEST).read_bytes()),
        "ids": ids,
        "files": files,
    }
    (staging / RELEASE_JSON).write_text(json_text(record), encoding="utf-8")


def build_release(inputs: ReleaseInputs, out: Path, record_on: date | None = None, releases: Path = RELEASES) -> Path:
    """Build, gate and place the bundle at `out/<tag>/`. Without `record_on`, the tag must already be recorded in
    `releases` with today's IDs (the owner records it before tagging); with it, the bundle is built and gated, then
    the tag is recorded on that date."""
    if inputs.real_book is None or not (inputs.real_book / METADATA).is_file():
        raise ReleaseError(
            "the real-ticker build is missing: run `uv run casebook build --real-tickers`; the release's gate refuses "
            "any file that came from it, so it needs it to compare"
        )
    if read_manifest(inputs.book).version != BOOK_VERSION:
        raise ReleaseError(f"{inputs.book} is book {read_manifest(inputs.book).version}, not {BOOK_VERSION}")
    try:
        errata = load_errata(inputs.published / "errata.json")
        recorded = load_releases(releases)
    except (ErrataError, ReleaseRecordError) as error:
        raise ReleaseError(str(error)) from error
    ledger = load_ledger(LEDGER)
    # What the release is built from is checked first, before anything is built: the book against its manifest,
    # the published folders for files the release would not take, then the stable-ID rule and the record.
    problems = book_problems(inputs.book) + stray_problems(inputs, recorded)
    if problems:
        raise ReleaseError("the release's inputs are not as published:\n  " + "\n  ".join(problems))
    ids = id_digests(inputs.book, inputs.tasks, inputs.published / "keys")
    before = [r for r in recorded if r.tag != tag()]
    problems = stable_id_problems(ids, BOOK_VERSION, before, errata, ledger)
    this = next((r for r in recorded if r.tag == tag()), None)
    if record_on is None and this is None:
        problems.append(
            f"{tag()} is not recorded in {releases.name}: record it with "
            "`uv run casebook release --preview --record --date <YYYY-MM-DD>` and commit it before tagging"
        )
    elif this is not None and (this.book_version != BOOK_VERSION or this.ids != ids):
        problems.append(f"{tag()} is recorded in {releases.name} with other IDs or another book version")
    if problems:
        raise ReleaseError("the release's IDs fail the stable-ID rule:\n  " + "\n  ".join(problems))
    staging = out / f"{tag()}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    try:
        _stage(inputs, staging)
        _release_json(staging, inputs, ids)
        problems = release_problems(
            staging, held_material(inputs.book, inputs.real_book, inputs.tasks, inputs.held_keys, inputs.repo / IMAGES)
        )
        if problems:
            raise ReleaseError("the release fails its gates:\n  " + "\n  ".join(problems))
        if record_on is not None:
            try:
                record_release(tag(), BOOK_VERSION, record_on, ids, errata, ledger, releases)
            except ReleaseRecordError as error:
                raise ReleaseError(str(error)) from error
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    target = out / tag()
    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)
    return target


def bundle_summary(bundle: Path) -> str:
    record = json.loads((bundle / RELEASE_JSON).read_text(encoding="utf-8"))
    return (
        f"{record['tag']} (book {record['book_version']}): {len(record['files'])} files, "
        f"{len(record['ids']['households'])} households, {len(record['ids']['tasks'])} tasks, into {bundle}"
    )
