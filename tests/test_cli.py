from pathlib import Path

import pytest

from casebook.cli import main

from .conftest import FEATURED, PUBLIC_HOUSEHOLDS, README, SCRIPTS


def test_build_check_and_site_from_the_command_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    book = tmp_path / "book"
    assert main(["build", "--seed", "2026", "--out", str(book), "--scripts", str(SCRIPTS)]) == 0
    assert f"built {PUBLIC_HOUSEHOLDS} households" in capsys.readouterr().out
    assert main(["check", "--book", str(book)]) == 0
    site = tmp_path / "site"
    none = str(tmp_path / "no-runs")
    assert main(["site", "--book", str(book), "--out", str(site), "--readme", str(README), "--runs", none]) == 0
    # The index and a page per public featured household.
    assert f"built {1 + len(FEATURED)} pages" in capsys.readouterr().out
    assert (site / "households" / "HH-4821.html").is_file()
