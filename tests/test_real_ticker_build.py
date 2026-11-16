"""Slice 4: a default build holds no real ticker, and the real-ticker build differs only in identifiers."""

import json
from pathlib import Path

import pytest

from casebook import BOOK_VERSION
from casebook.cli import main
from casebook.model.files import REAL_TICKERS
from casebook.published_text import text_of
from casebook.securities.master import load_master
from casebook.securities.scan import default_scan

from .conftest import SCRIPTS


def files_of(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def to_real(text: str) -> str:
    """Map a default build's text onto the real-ticker build's: each alias becomes its ticker."""
    for security in sorted(load_master(), key=lambda s: len(s.alias), reverse=True):
        text = text.replace(security.alias, security.real_ticker)
    return text


def test_a_default_build_holds_no_real_ticker_or_name_in_any_file(book: Path) -> None:
    scan = default_scan()
    leaks = [(name, hit) for name, data in files_of(book).items() for hit in scan.find(text_of(name, data))]
    assert leaks == []


def test_the_real_ticker_build_goes_to_out_real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["build", "--seed", "2026", "--real-tickers", "--scripts", str(SCRIPTS)]) == 0
    metadata = json.loads((tmp_path / "out" / "real" / BOOK_VERSION / "metadata.json").read_text())
    assert metadata["securities"] == REAL_TICKERS
    assert not (tmp_path / "out" / "book").exists()


def test_the_real_ticker_build_is_the_default_build_with_identifiers_mapped(book: Path, real_book: Path) -> None:
    default, real = files_of(book), files_of(real_book)
    assert sorted(default) == sorted(real)
    compared = 0
    for name, data in default.items():
        if name == "manifest.json":
            continue  # holds the other files' hashes, which differ wherever a file names a security
        if name == "metadata.json":
            mapped = json.loads(data) | {"securities": REAL_TICKERS}
            assert mapped == json.loads(real[name])
        elif name.endswith(".pdf"):
            assert to_real(text_of(name, data)) == text_of(name, real[name]), name
        else:
            assert to_real(data.decode()) == real[name].decode(), name
        compared += 1
    assert compared == len(default) - 1
    shown = {h["household_id"] for h in json.loads(default["manifest.json"])["households"]}
    assert shown == {h["household_id"] for h in json.loads(real["manifest.json"])["households"]}


def test_the_mapping_is_not_vacuous(book: Path, real_book: Path) -> None:
    # The two builds differ: every alias the default build shows is a ticker in the real one.
    positions = "households/HH-4821/custodian/positions.csv"
    assert (book / positions).read_text() != (real_book / positions).read_text()
    assert "Larkspur Total Market Fund" in (book / positions).read_text()
    assert ",VTI," in (real_book / positions).read_text()
