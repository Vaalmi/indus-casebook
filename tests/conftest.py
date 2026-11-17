import json
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Playwright, sync_playwright

from casebook.build import build_book
from casebook.graders.jury import VARIABLES as JURY_VARIABLES
from casebook.publish.site_build import build_site

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "book" / "scripted"
README = ROOT / "README.md"
SEED = 2026
STANDIN = ROOT / "tests" / "standin" / "claude.py"


# The public featured households (archetypes 7 and 8 are held out until the freeze).
# Every household of the public book: the featured ones and the 72 drawn in the background (the 80 less the
# private pairs, drawn only with the private salt).
def built(book: Path) -> tuple[str, ...]:
    return tuple(h["household_id"] for h in json.loads((book / "manifest.json").read_text())["households"])


FEATURED = (
    "HH-1204",
    "HH-1587",
    "HH-2316",
    "HH-2749",
    "HH-3058",
    "HH-3462",
    "HH-4105",
    "HH-4633",
    "HH-4821",
    "HH-5271",
    "HH-5814",
    "HH-6047",
    "HH-6590",
    "HH-7350",
    "HH-9234",
    "HH-9571",
)


@pytest.fixture(scope="session")
def book(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("book") / "0.0.1"
    build_book(SEED, out, SCRIPTS)
    return out


@pytest.fixture(scope="session")
def full_book(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The public book whole: the featured households and the 72 public ones drawn in the background. Most tests
    use `book`, the featured households alone, which builds in a fraction of the time."""
    out = tmp_path_factory.mktemp("full") / "0.0.1"
    build_book(SEED, out, SCRIPTS, background=True)
    return out


@pytest.fixture(scope="session")
def real_book(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("real") / "0.0.1"
    build_book(SEED, out, SCRIPTS, real_tickers=True)
    return out


@pytest.fixture(scope="session")
def site(book: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("site") / "site"
    build_site(book, out, README)
    return out


@pytest.fixture
def book_copy(book: Path, tmp_path: Path) -> Path:
    copy = tmp_path / "book"
    shutil.copytree(book, copy)
    return copy


class StandIn:
    """The stand-in CLI's settings file, which a test changes to pick its behavior."""

    def __init__(self, folder: Path) -> None:
        self.config = folder / "standin.json"
        self.log = folder / "standin.jsonl"
        self.answer = folder / "answer.md"
        self.answer.write_text('The fee was right.\n```json\n{"finding": "no_fee_error"}\n```\n')
        self.set()

    def set(self, mode: str = "answer", skill: str = "reconciliation-as-of") -> None:
        """`skill` is the one the skill arm loads (the tests' runs are T-REC-01's); the checklist has only its own."""
        settings = {"mode": mode, "log": str(self.log), "answer": str(self.answer), "skill": skill}
        self.config.write_text(json.dumps(settings))


@pytest.fixture(autouse=True)
def no_live_juror(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test reaches a real juror (rule 13): each jury CLI is a command that does not exist, so a vote asked
    for by mistake is missing, until a test sets the stand-in jury (tests/jury_fixtures.py)."""
    for variable in JURY_VARIABLES.values():
        monkeypatch.setenv(variable, "casebook-no-live-juror")


@pytest.fixture
def standin_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> StandIn:
    cli = StandIn(tmp_path)
    monkeypatch.setenv("CASEBOOK_CLAUDE", f"{sys.executable} {STANDIN} --standin-config {cli.config}")
    monkeypatch.setenv("CASEBOOK_PRIVATE", str(tmp_path / "private"))
    return cli


@pytest.fixture
def standin(standin_cli: StandIn) -> Path:
    return standin_cli.log


@pytest.fixture(scope="session")
def playwright() -> Iterator[Playwright]:
    """One Playwright for the whole run: its sync API allows only one at a time."""
    with sync_playwright() as running:
        yield running


@pytest.fixture(scope="session")
def browser(playwright: Playwright) -> Iterator[Browser]:
    chromium = playwright.chromium.launch()
    yield chromium
    chromium.close()
