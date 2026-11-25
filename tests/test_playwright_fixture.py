"""The shared Playwright stops at the end of the test file that used it.

Playwright's sync API runs an asyncio loop in the test's thread for as long as it is open. Open for the whole session,
it broke every later `anyio.run` in that process: the CRM sandbox's tests failed on the one worker where a browser
test file ran first (Check run 45503528165, 24 November 2026, the first run in four workers).
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BROWSER_FILE = """
from playwright.sync_api import Playwright


def test_a_browser_test_starts_playwright(playwright: Playwright) -> None:
    assert playwright.chromium.name == "chromium"
"""

LOOP_FILE = """
import asyncio

import anyio


def test_a_later_file_runs_its_own_event_loop() -> None:
    anyio.run(asyncio.sleep, 0)
"""


def test_a_file_after_a_browser_test_file_can_run_an_event_loop(tmp_path: Path) -> None:
    (tmp_path / "test_1_browser.py").write_text(BROWSER_FILE)
    (tmp_path / "test_2_loop.py").write_text(LOOP_FILE)
    # The two files run in one process, in this order, as a worker may run a browser test file and then another;
    # the suite's own options (coverage, its threshold) are left out of this inner run.
    files = [str(tmp_path / "test_1_browser.py"), str(tmp_path / "test_2_loop.py")]
    ran = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "tests.conftest", "-o", "addopts=", *files],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "2 passed" in ran.stdout
