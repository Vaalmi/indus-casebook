"""The CRM sandbox a follow-up run records its follow-up in (docs/PLAN.md, slice 10).

Before each attempt the runner seeds a fresh sandbox, outside the workspace, with every household's CRM as it
stood at the task's cutoff (a real CRM holds every client, so a write may go to the wrong one), and points the
CLI at the sandbox's MCP server. After the attempt the diff of its final state from the seed goes in the run
record, and the follow-up task is graded on it.
"""

import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from casebook.crm import sandbox
from casebook.crm.diff import crm_diff
from casebook.model.files import CRM_JSON, household_dir, read_manifest
from casebook.runner.config import CRM_SERVER
from casebook.tasks.fixtures import load_task_fixtures
from casebook.tasks.task import BOOK

STATE = "state.json"
MCP_CONFIG = "mcp.json"


@dataclass(frozen=True)
class Sandbox:
    state: Path
    # The --mcp-config file that starts the sandbox's server over stdio.
    mcp_config: Path
    initial: dict[str, Any]

    def diff(self) -> dict[str, Any]:
        """Every record the attempt added, changed or removed, as the run record holds it."""
        return crm_diff(self.initial, sandbox.read_state(self.state)).to_dict()


def book_crms(book: Path, cutoff: date) -> dict[str, dict[str, Any]]:
    """Every household's CRM as it stood at the cutoff, by household ID, filtered as a workspace's fixtures are."""
    with tempfile.TemporaryDirectory(prefix="casebook-crm-") as folder:
        root = Path(folder)
        load_task_fixtures(book, BOOK, ("crm",), cutoff, root)
        return {
            h.household_id: json.loads((root / household_dir(h.household_id) / CRM_JSON).read_text(encoding="utf-8"))
            for h in read_manifest(book).households
        }


def seed(book: Path, cutoff: date, folder: Path) -> Sandbox:
    """A fresh sandbox in `folder`, which must not exist yet: the state file and the MCP config naming it."""
    folder.mkdir(parents=True)
    state = (folder / STATE).resolve()
    initial = sandbox.write_state(state, book_crms(book, cutoff))
    server = {"type": "stdio", "command": sys.executable, "args": ["-m", "casebook.crm.server", "--state", str(state)]}
    mcp_config = folder / MCP_CONFIG
    mcp_config.write_text(json.dumps({"mcpServers": {CRM_SERVER: server}}, indent=2) + "\n", encoding="utf-8")
    return Sandbox(state, mcp_config.resolve(), initial)
