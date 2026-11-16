import shutil
from pathlib import Path

import pytest

from casebook.build import build_book
from casebook.publish.site_build import build_site

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "book" / "scripted"
README = ROOT / "README.md"
SEED = 2026


@pytest.fixture(scope="session")
def book(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("book") / "0.0.1"
    build_book(SEED, out, SCRIPTS)
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
