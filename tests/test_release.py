"""`casebook release --preview` end to end (docs/PLAN.md, slice 16): the bundle built from the real committed release
files and the public book, its layout, its record, and its refusals. Each gate's own refusals are tested one by one
in tests/test_release_gates.py; here, that the release runs them and refuses on any."""

import hashlib
import json
import re
import shutil
from datetime import date
from pathlib import Path

import pytest

from casebook.cli import main
from casebook.notice import NOTICE, contains_notice
from casebook.publish import release as release_module
from casebook.publish.release import ReleaseError, ReleaseInputs, build_release, tag
from casebook.publish.release_gates import HeldMaterial, held_material, release_problems
from casebook.publish.release_record import load_releases
from casebook.publish.review_packet import packet_zip, write_review_packet
from casebook.publish.zips import read_zip
from tests.conftest import FEATURED

ROOT = Path(__file__).resolve().parents[1]
DAY = date(2026, 11, 19)


def _empty_record(path: Path) -> None:
    """A record of no release, whatever the owner has recorded in the committed one (reviewers A and B, slice 16
    round 1, D1)."""
    path.write_text(json.dumps({"notice": NOTICE, "releases": []}), encoding="utf-8")


@pytest.fixture(scope="module")
def released(full_book: Path, real_book: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """The bundle, built and recorded once from the committed release files against an empty record."""
    work = tmp_path_factory.mktemp("release")
    releases = work / "releases.json"
    _empty_record(releases)
    inputs = ReleaseInputs(book=full_book, real_book=real_book, repo=ROOT, held_keys=work / "held-keys")
    return build_release(inputs, work / "out", DAY, releases), releases


def test_the_bundle_is_laid_out_as_the_owner_chose(released: tuple[Path, Path]) -> None:
    bundle, _ = released
    assert bundle.name == "v0.1.0" == tag()
    assert sorted(p.name for p in bundle.iterdir()) == [
        "LICENSE",
        "LICENSE-DATA",
        "NOTICE.txt",
        "README.md",
        "audit",
        "book",
        "docs",
        "errata.json",
        "freeze.json",
        "keys",
        "packets",
        "release.json",
        "results",
        "runs",
        "site",
    ]
    packets = sorted(p.name for p in (bundle / "packets").iterdir())
    assert packets == [f"{h}.zip" for h in FEATURED]
    assert sorted(p.name for p in (bundle / "site" / "packets").iterdir()) == packets
    assert not list((bundle / "book").rglob("tax_summary.json"))
    assert (bundle / "audit" / "audit-log.csv").is_file()
    # The README's images ship with it (reviewer A, slice 16 round 1, D2).
    assert {p.name for p in (bundle / "docs" / "images").iterdir()} == {
        p.name for p in (ROOT / "docs" / "images").iterdir()
    } | {"NOTICE.txt"}
    assert contains_notice((bundle / "audit" / "AUDIT.md").read_text().split("\n\n")[0])
    assert len(list((bundle / "runs").rglob("*.json"))) == len(list((ROOT / "published" / "runs").rglob("*.json")))


def test_release_json_names_the_book_and_every_file(released: tuple[Path, Path], full_book: Path) -> None:
    bundle, _ = released
    record = json.loads((bundle / "release.json").read_text())
    assert record["notice"] == NOTICE
    assert (record["tag"], record["package_version"], record["book_version"], record["seed"]) == (
        "v0.1.0",
        "0.1.0",
        "0.0.1",
        2026,
    )
    assert record["book_manifest_sha256"] == hashlib.sha256((full_book / "manifest.json").read_bytes()).hexdigest()
    on_disk = {p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file()} - {"release.json"}
    assert set(record["files"]) == on_disk
    for name in ("packets/HH-4821.zip", "README.md", "site/index.html"):
        assert record["files"][name] == hashlib.sha256((bundle / name).read_bytes()).hexdigest()
    assert len(record["ids"]["households"]) == 92 and len(record["ids"]["tasks"]) == 24


def test_a_packet_holds_its_source_files_and_answer_sheet_and_no_tax_answer(released: tuple[Path, Path]) -> None:
    bundle, _ = released
    members = read_zip((bundle / "packets" / "HH-5271.zip").read_bytes())
    assert "answer-sheet.json" in members and "NOTICE.txt" in members
    assert {n.split("/")[2] for n in members if n.startswith("households/")} == {
        "crm",
        "custodian",
        "documents",
        "portfolio",
    }
    assert not [n for n in members if "tax_summary" in n or "/returns/" in n or n.startswith("sealed/")]


def test_the_release_is_recorded_and_a_second_release_of_the_same_book_is_accepted(
    released: tuple[Path, Path], full_book: Path, real_book: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, releases = released
    (recorded,) = load_releases(releases)
    assert (recorded.tag, recorded.book_version, recorded.date) == ("v0.1.0", "0.0.1", DAY)
    # Rebuilding the recorded tag needs no --record; the bundle's gates are tested above, so stage nothing here.
    monkeypatch.setattr(release_module, "_stage", _stage_nothing)
    monkeypatch.setattr(release_module, "release_problems", _no_problems)
    inputs = ReleaseInputs(book=full_book, real_book=real_book, repo=ROOT, held_keys=tmp_path / "keys")
    assert build_release(inputs, tmp_path / "out", releases=releases).name == "v0.1.0"


def _stage_nothing(inputs: ReleaseInputs, staging: Path) -> None:
    staging.mkdir(parents=True)


def _no_problems(bundle: Path, held: HeldMaterial) -> list[str]:
    return []


def _a_held_key(bundle: Path, held: HeldMaterial) -> list[str]:
    return ["keys/T-TAX-01.json: a held key"]


def _inputs(full_book: Path, real_book: Path | None, tmp_path: Path) -> ReleaseInputs:
    return ReleaseInputs(book=full_book, real_book=real_book, repo=ROOT, held_keys=tmp_path / "keys")


def test_an_unrecorded_tag_is_refused_before_anything_is_built(
    full_book: Path, real_book: Path, tmp_path: Path
) -> None:
    releases = tmp_path / "releases.json"
    _empty_record(releases)
    with pytest.raises(ReleaseError, match=r"v0\.1\.0 is not recorded in releases\.json"):
        build_release(_inputs(full_book, real_book, tmp_path), tmp_path / "out", releases=releases)
    assert not (tmp_path / "out").exists()


def test_a_changed_id_with_no_new_version_and_errata_entry_is_refused(
    released: tuple[Path, Path], full_book: Path, real_book: Path, tmp_path: Path
) -> None:
    """The plan's criterion: a household whose meaning changed since the release, under the same book version."""
    _, releases = released
    record = json.loads(releases.read_text())
    record["releases"][0]["tag"] = "v0.0.9"
    record["releases"][0]["ids"]["households"]["HH-4821"] = "0" * 64
    changed = tmp_path / "releases.json"
    changed.write_text(json.dumps(record))
    with pytest.raises(ReleaseError, match="HH-4821"):
        build_release(_inputs(full_book, real_book, tmp_path), tmp_path / "out", DAY, changed)
    assert not (tmp_path / "out").exists()


def test_a_bundle_failing_a_gate_is_refused_and_leaves_nothing(
    full_book: Path, real_book: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    releases = tmp_path / "releases.json"
    _empty_record(releases)
    monkeypatch.setattr(release_module, "_stage", _stage_nothing)
    monkeypatch.setattr(release_module, "release_problems", _a_held_key)
    with pytest.raises(ReleaseError, match="a held key"):
        build_release(_inputs(full_book, real_book, tmp_path), tmp_path / "out", DAY, releases)
    assert list((tmp_path / "out").iterdir()) == []
    assert load_releases(releases) == []


def test_a_release_without_the_real_ticker_build_is_refused(full_book: Path, tmp_path: Path) -> None:
    with pytest.raises(ReleaseError, match="build --real-tickers"):
        build_release(_inputs(full_book, tmp_path / "missing", tmp_path), tmp_path / "out", DAY)


def test_the_command_needs_a_date_to_record(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["release", "--preview", "--record"]) == 1
    assert "--record needs --date" in capsys.readouterr().err


def test_the_review_packet_copied_into_the_bundle_is_refused(
    released: tuple[Path, Path], full_book: Path, real_book: Path, tmp_path: Path
) -> None:
    """The owner's choice 4: the review packet holds the tax summaries, so it is never part of the release."""
    bundle, _ = released
    copy = tmp_path / "bundle"
    shutil.copytree(bundle, copy)
    folder = write_review_packet(full_book, tmp_path / "review")
    shutil.copyfile(packet_zip(folder), copy / "review-packet.zip")
    held = held_material(full_book, real_book, ROOT / "tasks" / "public", tmp_path / "keys", ROOT / "docs" / "images")
    problems = release_problems(copy, held)
    assert any(p.startswith("review-packet.zip!tax_summaries/") for p in problems), problems[:5]


def _repo_with(tmp_path: Path, stray: str) -> Path:
    """A copy of the repo's published folders and tasks with one stray file added."""
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "published", repo / "published")
    shutil.copytree(ROOT / "tasks" / "public", repo / "tasks" / "public")
    (repo / "published" / stray).parent.mkdir(parents=True, exist_ok=True)
    (repo / "published" / stray).write_text('{"task_id": "T-TAX-01", "grade": {"score": 100}}')
    return repo


@pytest.mark.parametrize(
    "stray",
    ["audit/held-result.json", "audit/export.zip", "results/summary.csv", "keys/0.0.1/T-TAX-01.json", "keys/x.json"],
)
def test_a_stray_file_in_a_published_folder_stops_the_release(
    full_book: Path, real_book: Path, tmp_path: Path, stray: str
) -> None:
    """Reviewers A and B, slice 16 round 1: a file copied into published/audit/ shipped whatever it held."""
    repo = _repo_with(tmp_path, stray)
    _empty_record(tmp_path / "releases.json")
    inputs = ReleaseInputs(book=full_book, real_book=real_book, repo=repo, held_keys=tmp_path / "keys")
    with pytest.raises(ReleaseError, match=re.escape(f"published/{stray}: not")):
        build_release(inputs, tmp_path / "out", DAY, tmp_path / "releases.json")


def test_a_book_file_changed_after_its_build_stops_the_release(
    full_book: Path, real_book: Path, tmp_path: Path
) -> None:
    """Reviewer B, slice 16 round 1, S6: a sealed fee changed without its manifest kept every ID's digest."""
    _empty_record(tmp_path / "releases.json")
    book = tmp_path / "0.0.1"
    shutil.copytree(full_book, book)
    events = book / "sealed" / "HH-7350" / "events.json"
    events.write_text(events.read_text().replace("-1855.93", "1.00", 1))
    with pytest.raises(ReleaseError, match=r"sealed/HH-7350/events\.json: its bytes"):
        build_release(_inputs(book, real_book, tmp_path), tmp_path / "out", DAY, tmp_path / "releases.json")
