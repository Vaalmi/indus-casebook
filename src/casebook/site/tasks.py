"""Task pages: what each arm produced on a task, graded, with the failure marked and the run named."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from casebook.tasks.task import HELD_GRADERS, HELD_WORKFLOWS, Task, load_task

ARM_ORDER = ("basic", "checklist", "skill")
ARM_NAMES = {"basic": "Basic prompt", "checklist": "Checklist", "skill": "Skill"}
TOOL = "Claude Code"


class UnnamedResultError(ValueError):
    """docs/SPEC.md, Rules: a result without tool, version, model and date cannot be published."""


@dataclass(frozen=True)
class ArmView:
    arm: str
    name: str
    record: dict[str, Any] | None
    runs: int

    @property
    def graded(self) -> bool:
        return bool(self.record and self.record.get("grade"))

    @property
    def tool(self) -> str:
        return f"{TOOL} {str((self.record or {}).get('cli_version', '')).split(' ')[0]}"

    @property
    def models(self) -> str:
        return ", ".join((self.record or {}).get("models_reported") or [])

    @property
    def effort(self) -> str:
        return str(((self.record or {}).get("settings") or {}).get("effort") or "")

    @property
    def date(self) -> str:
        return str((self.record or {}).get("started_utc", ""))[:10]


# How the CLI names an MCP server's tools, and the CRM sandbox's.
MCP_PREFIX = "mcp__"
CRM_PREFIX = "mcp__crm__"


@dataclass(frozen=True)
class TaskView:
    task: Task
    arms: tuple[ArmView, ...]
    key: dict[str, Any] | None

    @property
    def file_tools(self) -> tuple[str, ...]:
        return tuple(t for t in self.task.allowed_tools if not t.startswith(MCP_PREFIX))

    @property
    def crm_tools(self) -> tuple[str, ...]:
        """The CRM sandbox's tools the task allows, by the names the sandbox gives them."""
        return tuple(t.removeprefix(CRM_PREFIX) for t in self.task.allowed_tools if t.startswith(CRM_PREFIX))

    @property
    def held(self) -> bool:
        """A tax-lot and RMD task, or a reconciliation task whose key computes an RMD: its page shows
        sources and outputs only, with no verdict, no failure marking and no conclusion, until review."""
        return self.task.workflow in HELD_WORKFLOWS or self.task.grader in HELD_GRADERS


def require_named(record: dict[str, Any], where: str) -> None:
    if record.get("state") == "failed":
        return
    missing = [f for f in ("cli_version", "models_reported", "started_utc") if not record.get(f)]
    if missing:
        raise UnnamedResultError(f"{where} lacks {', '.join(missing)}, so it cannot be published")


def load_records(runs: Path) -> dict[str, list[dict[str, Any]]]:
    by_task: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(runs.glob("*/*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        require_named(record, path.name)
        by_task.setdefault(str(record["task_id"]), []).append(record)
    return by_task


def task_views(tasks: Path, runs: Path, keys: Path | None) -> list[TaskView]:
    if not runs.is_dir():
        return []
    records = load_records(runs)
    views: list[TaskView] = []
    for task_id in sorted(records):
        task = load_task(tasks / f"{task_id}.toml")
        arms: list[ArmView] = []
        for arm in ARM_ORDER:
            mine = sorted((r for r in records[task_id] if r["arm"] == arm), key=lambda r: str(r["started_utc"]))
            arms.append(ArmView(arm, ARM_NAMES[arm], mine[-1] if mine else None, len(mine)))
        key_file = keys / f"{task_id}.json" if keys else None
        key = json.loads(key_file.read_text(encoding="utf-8")) if key_file and key_file.is_file() else None
        views.append(TaskView(task, tuple(arms), key))
    return views
