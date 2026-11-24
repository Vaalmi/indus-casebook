"""Task pages: what each arm produced on a task, graded, with the failure marked and the run named."""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from casebook.review_statement import ReviewStatement, is_held, notice_for_task
from casebook.runner.record import REGRADED
from casebook.tasks.task import Task, find_task

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
    # A tax task until a review statement's scope names it: its page shows sources and outputs only, with no
    # verdict, no failure marking and no conclusion (`casebook.review_statement.is_held`).
    held: bool
    # The notice its page carries: the reviewed notice for a tax task a review statement covers.
    notice: str

    @property
    def file_tools(self) -> tuple[str, ...]:
        return tuple(t for t in self.task.allowed_tools if not t.startswith(MCP_PREFIX))

    @property
    def crm_tools(self) -> tuple[str, ...]:
        """The CRM sandbox's tools the task allows, by the names the sandbox gives them."""
        return tuple(t.removeprefix(CRM_PREFIX) for t in self.task.allowed_tools if t.startswith(CRM_PREFIX))


# How the CLI names itself and its version: `claude --version` prints "2.1.304 (Claude Code)".
_TOOL = re.compile(r"\(([^()]+)\)\s*$")
_VERSION = re.compile(r"\d+(?:\.\d+)+(?=\s|$)")


def cli_name(cli_version: str) -> tuple[str | None, str | None]:
    """The tool and the version a record's `cli_version` names, each None where it names none."""
    text = cli_version.strip()
    tool = _TOOL.search(text)
    version = _VERSION.match(text)
    return (tool.group(1).strip() if tool else None, version.group(0) if version else None)


def _dated(value: Any) -> bool:
    try:
        datetime.fromisoformat(str(value))
    except ValueError:
        return False
    return True


def _models_named(value: Any) -> bool:
    """A non-empty list of models, each named: not "", not blanks (reviewers A and B, slice 13 round 1)."""
    return (
        isinstance(value, list) and bool(value) and all(isinstance(m, str) and m.strip() for m in value)  # pyright: ignore[reportUnknownVariableType]
    )


def require_named(record: dict[str, Any], where: str) -> None:
    """docs/SPEC.md, Rules: "a result without tool, version, model and date cannot be published". A failed run
    is no result: it is never scored, and its CLI may not have started to name itself."""
    if record.get("state") == "failed":
        return
    tool, version = cli_name(str(record.get("cli_version") or ""))
    missing = [
        *([] if tool else ["the tool (cli_version)"]),
        *([] if version else ["the version (cli_version)"]),
        *([] if _models_named(record.get("models_reported")) else ["models_reported"]),
        *([] if _dated(record.get("started_utc")) else ["started_utc"]),
    ]
    if missing:
        raise UnnamedResultError(f"{where} lacks {', '.join(missing)}, so it cannot be published")


def load_records(runs: Path) -> dict[str, list[dict[str, Any]]]:
    """Every run record under the published runs, at any depth, each named: a record outside `<task>/` is still
    checked, as the site build would still copy it (reviewer A, slice 13 round 1)."""
    by_task: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(runs.rglob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        require_named(record, path.relative_to(runs).as_posix())
        by_task.setdefault(str(record["task_id"]), []).append(record)
    return by_task


def graded_under(record: dict[str, Any]) -> Any:
    """The freeze a run was graded under: the regrade's, if it was graded again, else the one it ran under."""
    return (record.get(REGRADED) or {}).get("freeze", record.get("freeze"))


class MixedFreezeError(UnnamedResultError):
    """A page whose arms ran under different freezes."""


def task_views(tasks: Path, runs: Path, keys: Path | None, statement: ReviewStatement | None = None) -> list[TaskView]:
    if not runs.is_dir():
        return []
    records = load_records(runs)
    views: list[TaskView] = []
    for task_id in sorted(records):
        task = find_task(tasks, task_id)
        arms: list[ArmView] = []
        for arm in ARM_ORDER:
            mine = sorted((r for r in records[task_id] if r["arm"] == arm), key=lambda r: str(r["started_utc"]))
            arms.append(ArmView(arm, ARM_NAMES[arm], mine[-1] if mine else None, len(mine)))
        # Results from two freezes are never shown side by side (docs/PLAN.md, the freeze's state table;
        # reviewers A and B, slice 12 round 1): a page's arms ran under one freeze, or before any, and were graded
        # under one: a regrade cut short leaves some arms graded under the new freeze (whole-branch review, A).
        freezes = {(a.record.get("freeze"), graded_under(a.record)) for a in arms if a.record is not None}
        if len(freezes) > 1:
            shown = ", ".join(
                sorted(f"ran {str(r)[:12] if r else 'none'}, graded {str(g)[:12] if g else 'none'}" for r, g in freezes)
            )
            raise MixedFreezeError(
                f"task {task_id}'s latest runs ran or were graded under different freezes ({shown}); "
                "rerun every arm, or finish the regrade"
            )
        key_file = keys / f"{task_id}.json" if keys else None
        key = json.loads(key_file.read_text(encoding="utf-8")) if key_file and key_file.is_file() else None
        views.append(TaskView(task, tuple(arms), key, is_held(task, statement), notice_for_task(task, statement)))
    return views
