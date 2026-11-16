import csv
import hashlib
import json
from pathlib import Path

import pytest

import casebook.build
from casebook.build import BuildError, build_book, refuse_real_identifiers
from casebook.model.files import (
    MANIFEST,
    METADATA,
    PRICES_CSV,
    REGISTRY,
    SOURCE_SETS,
    event_log_path,
    household_dir,
)
from casebook.notice import NOTICE

from .conftest import SCRIPTS, SEED

HOUSEHOLDS = ("HH-4821", "HH-7350")


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def test_the_pair_has_four_source_sets_an_event_log_and_one_registry_entry(book: Path) -> None:
    for household in HOUSEHOLDS:
        for source in SOURCE_SETS:
            assert any((book / household_dir(household) / source).iterdir()), (household, source)
        log = json.loads((book / event_log_path(household)).read_text())
        assert log["events"][0]["type"] == "opening"
    entries = json.loads((book / REGISTRY).read_text())["entries"]
    assert [(e["item_id"], e["household_id"], e["type"]) for e in entries] == [
        ("PI-0001", "HH-4821", "missed_fee_breakpoint")
    ]


def test_the_same_seed_builds_a_byte_identical_book(book: Path, tmp_path: Path) -> None:
    again = tmp_path / "again"
    build_book(SEED, again, SCRIPTS)
    assert tree_hash(again) == tree_hash(book)


def test_another_seed_builds_other_prices(book: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    build_book(SEED + 1, other, SCRIPTS)
    assert (other / PRICES_CSV).read_bytes() != (book / PRICES_CSV).read_bytes()


def test_a_new_version_redraws_no_price(book: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # docs/decisions/2026-11-16-version-in-the-price-seed.md: a release changes only what it corrects.
    monkeypatch.setattr(casebook.build, "BOOK_VERSION", "0.0.2")
    later = tmp_path / "later"
    build_book(SEED, later, SCRIPTS)
    assert json.loads((later / METADATA).read_text())["version"] == "0.0.2"
    assert (later / PRICES_CSV).read_bytes() == (book / PRICES_CSV).read_bytes()
    for household in HOUSEHOLDS:
        for name in ("custodian/positions.csv", "portfolio/billing.json"):
            where = f"households/{household}/{name}"
            assert (later / where).read_bytes() == (book / where).read_bytes(), where


def test_the_manifest_hashes_every_file(book: Path) -> None:
    manifest = json.loads((book / MANIFEST).read_text())
    on_disk = {p.relative_to(book).as_posix() for p in book.rglob("*") if p.is_file()} - {MANIFEST}
    assert set(manifest["files"]) == on_disk
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((book / name).read_bytes()).hexdigest() == digest
    assert [(h["household_id"], h["state"]) for h in manifest["households"]] == [(h, "emitted") for h in HOUSEHOLDS]


def test_the_data_metadata_carries_the_notice_and_the_data_licence(book: Path) -> None:
    metadata = json.loads((book / METADATA).read_text())
    assert metadata["notice"] == NOTICE
    assert metadata["licence"] == "CC-BY-4.0"


def test_every_price_in_the_price_file_is_labelled_synthetic(book: Path) -> None:
    with (book / PRICES_CSV).open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows and all(row["price_label"] == "synthetic" for row in rows)


@pytest.mark.parametrize("leak", [b"Holds 40 MSFT", b"a Microsoft position", b"Vanguard Total Bond Market fund"])
def test_a_default_build_refuses_a_real_ticker_or_name(leak: bytes) -> None:
    with pytest.raises(BuildError, match="real ticker or security name"):
        refuse_real_identifiers({"households/HH-0001/crm/notes.txt": leak})


def test_a_default_build_carries_aliases_only(book: Path) -> None:
    refuse_real_identifiers({p.relative_to(book).as_posix(): p.read_bytes() for p in book.rglob("*") if p.is_file()})
