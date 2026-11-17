"""The private pairs: the four background pairs the private set runs on, drawn only with the private salt.

No figure of a private pair appears here. A salted build uses a test salt, never the private one, and is
written to a temporary folder outside the repo.
"""

import json
from pathlib import Path
from typing import Any

import pytest

import casebook.build
from casebook.build import ID_LEDGER, BuildError, BuildResult, build_book
from casebook.checks import check_book
from casebook.cli import main
from casebook.generate.background import draw_pair
from casebook.model.ledger import load_ledger
from casebook.securities.market import Market, build_market
from casebook.securities.master import load_master

from .conftest import ROOT, SEED

# docs/SPEC.md, Private set, and the owner's decision of 16 November 2026: (archetype, pair).
PRIVATE = {(10, 3), (4, 2), (6, 4), (9, 2)}
TEST_SALT = "private-pairs-test-salt-5c1e"


def private_households() -> dict[str, tuple[int, int, str]]:
    """The eight households of the private pairs, read from the public ID ledger (an ID is not secret)."""
    ledger = load_ledger(ID_LEDGER)
    return {
        hh: (e.archetype, e.pair, e.role) for hh, e in ledger.households.items() if (e.archetype, e.pair) in PRIVATE
    }


def ids(archetype: int, pair: int) -> tuple[str, str]:
    by_role = {role: hh for hh, (a, p, role) in private_households().items() if (a, p) == (archetype, pair)}
    return by_role["trap"], by_role["twin"]


def sealed(book: Path) -> list[dict[str, Any]]:
    return json.loads((book / "sealed" / "households.json").read_text())["households"]


def roles(book: Path) -> dict[str, tuple[int, int, str]]:
    return {h["household_id"]: (h["archetype"], h["pair"], h["role"]) for h in sealed(book)}


@pytest.fixture(scope="module")
def market() -> Market:
    return build_market(load_master(), SEED)


@pytest.fixture(scope="module")
def salted(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The four private pairs' archetypes drawn with a test salt: their public pairs and the private ones."""
    out = tmp_path_factory.mktemp("salted") / "book"
    build_book(
        SEED,
        out,
        tmp_path_factory.mktemp("no-scripts"),
        background=True,
        background_archetypes=frozenset(a for a, _ in PRIVATE),
        private_salt=TEST_SALT,
    )
    return out


def text_files(book: Path) -> dict[str, str]:
    return {
        p.relative_to(book).as_posix(): p.read_text(encoding="utf-8")
        for p in book.rglob("*")
        if p.is_file() and p.suffix != ".pdf"
    }


def test_the_ledger_keeps_the_eight_private_households() -> None:
    households = private_households()
    assert len(households) == 8
    assert sorted((a, p, role) for a, p, role in households.values()) == sorted(
        (a, p, role) for a, p in PRIVATE for role in ("trap", "twin")
    )


def test_a_public_build_holds_no_private_pair_and_no_file_names_one(full_book: Path) -> None:
    assert not {(h["archetype"], h["pair"]) for h in sealed(full_book)} & PRIVATE
    numbers = [hh.removeprefix("HH-") for hh in private_households()]
    # A household's ID, and the account, transaction and record IDs drawn from its number.
    marks = [m for n in numbers for m in (f"HH-{n}", f"SYN-{n}", f"-{n}-")]
    named = [(name, mark) for name, text in text_files(full_book).items() for mark in marks if mark in text]
    assert named == []
    tasks = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "tasks").rglob("*.toml")}
    assert [(name, hh) for name, text in tasks.items() for hh in private_households() if hh in text] == []


def test_a_salted_build_holds_all_eight_private_households_and_passes_every_check(salted: Path) -> None:
    drawn = roles(salted)
    assert private_households().items() <= drawn.items()
    # Archetypes 4, 6, 9 and 10, pairs 2 to 5 each: 32 households, nine checks each.
    assert len(drawn) == 32
    report = check_book(salted)
    assert report.passed and len(report.lines) == 32 * 9


def test_the_salt_enters_no_built_file(salted: Path) -> None:
    assert [name for name, text in text_files(salted).items() if TEST_SALT in text] == []


@pytest.mark.parametrize(("archetype", "pair"), sorted(PRIVATE))
def test_a_salted_draw_differs_from_the_burned_unsalted_one(market: Market, archetype: int, pair: int) -> None:
    # The unsalted draw is the one the public repo stated answers for; it is drawn here only to compare.
    burned = draw_pair(SEED, archetype, pair, *ids(archetype, pair), market)
    drawn = draw_pair(SEED, archetype, pair, *ids(archetype, pair), market, TEST_SALT)
    for new, old in zip(drawn, burned, strict=True):
        assert new.household.household_id == old.household.household_id
        assert {p.name for p in new.household.members}.isdisjoint({p.name for p in old.household.members})
        assert new.accounts != old.accounts


def test_a_different_salt_gives_a_different_draw_and_the_same_salt_the_same(market: Market) -> None:
    trap, twin = ids(10, 3)
    one = draw_pair(SEED, 10, 3, trap, twin, market, "one")
    assert draw_pair(SEED, 10, 3, trap, twin, market, "one") == one
    assert draw_pair(SEED, 10, 3, trap, twin, market, "two") != one


def test_a_salted_build_refuses_the_repo_as_its_output(tmp_path: Path) -> None:
    with pytest.raises(BuildError, match="a held-out build is written outside the public repo"):
        build_book(SEED, ROOT / "out" / "private-pairs-test", tmp_path, background=True, private_salt=TEST_SALT)
    assert not (ROOT / "out" / "private-pairs-test").exists()


def test_the_cli_writes_the_salt_once_and_reuses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    private = tmp_path / "private"
    monkeypatch.setenv("CASEBOOK_PRIVATE", str(private))
    # The private tasks run on this build: the real tickers, into $CASEBOOK_PRIVATE. The folder here holds no
    # held-out scripts, so the build is the public 88 and the eight private households.
    assert main(["build", "--seed", "2026", "--held-out", "--real-tickers"]) == 0
    out, err = capsys.readouterr()
    salt_file = private / "book" / "private_salt"
    assert "wrote a new private salt" in err and str(salt_file) in err
    assert "built 96 households, " in out and str(private / "out" / "real" / "0.0.1") in out
    salt = salt_file.read_text().strip()
    assert len(salt) == 64 and int(salt, 16) >= 0
    book = private / "out" / "real" / "0.0.1"
    assert private_households().items() <= roles(book).items()
    assert [name for name, text in text_files(book).items() if salt in text] == []

    asked: list[str | None] = []

    def recorded(*_args: Any, private_salt: str | None = None, **_kwargs: Any) -> BuildResult:
        asked.append(private_salt)
        return BuildResult(tmp_path / "book", (), 0)

    monkeypatch.setattr(casebook.build, "build_book", recorded)
    assert main(["build", "--held-out", "--out", str(tmp_path / "again")]) == 0
    assert "private salt" not in capsys.readouterr().err
    assert asked == [salt] and salt_file.read_text().strip() == salt
    # A public build draws no private pair.
    assert main(["build", "--out", str(tmp_path / "public")]) == 0
    assert asked == [salt, None]
