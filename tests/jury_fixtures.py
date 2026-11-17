"""The stand-in tone jury: the three jury CLIs pointed at stand-ins, so the checks never call a model
(docs/CODE_STANDARDS.md rule 13). A test sets each juror's behavior through `StandInJury.set`."""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.jury import VARIABLES

STANDINS = Path(__file__).resolve().parent / "standin"
SCRIPTS = {"claude": STANDINS / "jury_claude.py", "codex": STANDINS / "codex.py", "agy": STANDINS / "agy.py"}


class StandInJury:
    """Each jury CLI's stand-in settings file and call log, by CLI name."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        for cli in SCRIPTS:
            self.set(cli)

    def config(self, cli: str) -> Path:
        return self.folder / f"jury-{cli}.json"

    def log(self, cli: str) -> Path:
        return self.folder / f"jury-{cli}.jsonl"

    def set(self, cli: str, **settings: Any) -> None:
        """mode (vote, error, api_error for claude, timeout), score, reason, or reply (sent as written)."""
        self.config(cli).write_text(json.dumps({"log": str(self.log(cli)), **settings}))

    def calls(self, cli: str) -> list[dict[str, Any]]:
        log = self.log(cli)
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def use_standin_jury(folder: Path, monkeypatch: pytest.MonkeyPatch) -> StandInJury:
    """Point CASEBOOK_JURY_CLAUDE, CASEBOOK_JURY_CODEX and CASEBOOK_JURY_AGY at the stand-ins, settings in folder."""
    folder.mkdir(exist_ok=True)
    jury = StandInJury(folder)
    for cli, script in SCRIPTS.items():
        monkeypatch.setenv(VARIABLES[cli], f"{sys.executable} {script} --standin-config {jury.config(cli)}")
    return jury


@pytest.fixture
def standin_jury(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> StandInJury:
    """The stand-in jury, each juror voting 4 unless a test sets otherwise."""
    return use_standin_jury(tmp_path / "jury", monkeypatch)
