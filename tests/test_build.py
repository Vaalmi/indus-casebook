import csv
import hashlib
import json
import shutil
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
from casebook.published_text import text_of
from casebook.securities.market import build_market
from casebook.securities.master import load_master

from .conftest import FEATURED, SCRIPTS, SEED

HOUSEHOLDS = FEATURED


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
        ("PI-0001", "HH-4821", "missed_fee_breakpoint"),
        ("PI-0002", "HH-1204", "backdoor_roth_pro_rata"),
        ("PI-0003", "HH-2316", "niit_threshold"),
        ("PI-0004", "HH-3058", "rsu_basis_missing"),
        ("PI-0005", "HH-4105", "conversion_ira_basis"),
        ("PI-0006", "HH-5271", "first_rmd_401k_shortfall"),
        ("PI-0007", "HH-6047", "qcd_evidenced_in_crm_only"),
        ("PI-0010", "HH-9234", "cross_account_wash_sale"),
    ]


def test_the_same_seed_builds_a_byte_identical_book(book: Path, tmp_path: Path) -> None:
    again = tmp_path / "again"
    build_book(SEED, again, SCRIPTS)
    assert tree_hash(again) == tree_hash(book)


def test_another_seed_draws_other_prices() -> None:
    # The featured scripts are tuned to seed 2026's prices (a planter refuses a situation that no
    # longer holds), so the seed's effect is shown on the market itself.
    master = load_master()
    assert build_market(master, SEED + 1).prices != build_market(master, SEED).prices


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


@pytest.mark.parametrize("leak", ["Holds 40 MSFT", "a Microsoft position", "Vanguard Total Bond Market fund"])
def test_a_default_build_refuses_a_real_ticker_or_name(leak: str) -> None:
    with pytest.raises(BuildError, match="real ticker or security name"):
        refuse_real_identifiers({"households/HH-0001/crm/notes.txt": leak})


def test_a_default_build_carries_aliases_only(book: Path) -> None:
    files = {p.relative_to(book).as_posix(): p for p in book.rglob("*") if p.is_file()}
    refuse_real_identifiers({name: text_of(name, path.read_bytes()) for name, path in files.items()})


def test_the_whole_public_book_builds_96_households_byte_for_byte_again(full_book: Path, tmp_path: Path) -> None:
    # Slice 6: ten archetypes, five pairs each, less the four held out until the freeze (archetypes 7
    # and 8's featured pairs), which the whole book in $CASEBOOK_PRIVATE adds back for 100.
    manifest = json.loads((full_book / MANIFEST).read_text())
    assert len(manifest["households"]) == 96
    sealed = json.loads((full_book / "sealed" / "households.json").read_text())["households"]
    pairs = {(h["archetype"], h["pair"]) for h in sealed}
    assert len(pairs) == 48 and {p for _, p in pairs} == {1, 2, 3, 4, 5}
    again = tmp_path / "again"
    build_book(SEED, again, SCRIPTS, background=True)
    assert (again / MANIFEST).read_bytes() == (full_book / MANIFEST).read_bytes()


def test_a_household_that_overdraws_an_account_fails_the_build(tmp_path: Path) -> None:
    # Reviewers A and B, slice 6 round 1: drawn IRAs ended below zero; so did the featured
    # archetype-2 twin's, whose IRA cash could not cover its purchase and fees.
    scripts = tmp_path / "scripted"
    shutil.copytree(SCRIPTS, scripts)
    path = scripts / "archetype-2" / "HH-2749.toml"
    text = path.read_text()
    assert text.count('cash = "5000.00"') == 1
    path.write_text(text.replace('cash = "5000.00"', 'cash = "3500.00"'))
    with pytest.raises(BuildError, match=r"HH-2749: SYN-27490002 holds -19\.78 in cash on 2026-04-15"):
        build_book(SEED, tmp_path / "book", scripts)
