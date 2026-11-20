"""`casebook release --preview`: the versioned bundle of the preview release (docs/PLAN.md, slice 16), built in a
staging folder from the checked default book and the committed release files, gated whole, then moved into place.

The layout and the readings behind it are the owner's choices of 19 November 2026
(docs/decisions/2026-11-19-slice16-release-choices.md): tag v<package version> ships the book under its own version;
the site carries the case packets; the review packet is never part of it."""

import hashlib
import json
import shutil
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
    ReleaseRecordError,
    id_digests,
    load_releases,
    record_release,
    stable_id_problems,
)
from casebook.publish.site_build import SiteBuildError, build_site
from casebook.site.errata import ErrataError, load_errata
from casebook.site.tasks import UnnamedResultError

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


def _with_notice(source: Path, target: Path) -> None:
    data = json.loads(source.read_text(encoding="utf-8"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json_text({**data, "notice": NOTICE}), encoding="utf-8")


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
    for key in sorted((published / "keys" / manifest.version).glob("*.json")):
        _with_notice(key, staging / "keys" / key.name)
    _with_notice(published / "freeze.json", staging / "freeze.json")
    shutil.copyfile(published / "errata.json", staging / "errata.json")
    _copy_tree(published / "results", staging / "results")
    _copy_tree(published / "audit", staging / "audit")
    audit = staging / "audit" / AUDIT_NOTES
    audit.write_text(f"> **{NOTICE_HEADLINE}**{NOTICE.removeprefix(NOTICE_HEADLINE)}\n\n" + audit.read_text(), "utf-8")
    for folder in ("keys", "audit", "site"):
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
    # The stable-ID rule and the record need only the book and the tasks: refuse before building anything.
    ids = id_digests(inputs.book, inputs.tasks)
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
            staging, held_material(inputs.book, inputs.real_book, inputs.tasks, inputs.held_keys)
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
