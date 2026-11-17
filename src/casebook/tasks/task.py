"""The task file: prompt, fixtures, allowed tools, expected output, grader and justified conclusion."""

import hashlib
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from casebook.model.dates import parse_date
from casebook.model.files import SOURCE_SETS
from casebook.model.ledger import BOOK
from casebook.tasks.schemas import compliance_prompt_problems, compliance_schema_problems

__all__ = [
    "BOOK",
    "HELD_GRADERS",
    "HELD_WORKFLOWS",
    "WORKFLOWS",
    "Task",
    "TaskFormatError",
    "find_task",
    "load_task",
    "parse_task",
]

WORKFLOWS = ("reconciliation", "meeting", "tax_lot_rmd", "compliance")
# Tax-lot and RMD keys and verdicts are held until the tax review (docs/PLAN.md, Choices): every
# tax-lot and RMD task's, and any other task's whose key computes a tax-lot, RMD or other tax figure: an RMD
# in reconciliation; a Form 8606 taxable amount, the net investment income tax or the SALT limit, or the
# households with a tax surprise, in meeting; a released lot's basis and a sale's gain, or a conversion's
# taxable amount, in compliance.
HELD_WORKFLOWS = ("tax_lot_rmd",)
HELD_GRADERS = (
    "ira_distributions",
    "backdoor_roth_follow_up",
    "niit_follow_up",
    "tax_surprises",
    "concentration_basis",
    "conversion_documentation",
)
TASK_FIELDS = (
    "task_id",
    "workflow",
    "household_id",
    "cutoff",
    "prompt",
    "fixtures",
    "allowed_tools",
    "expected_output",
    "grader",
    "justified_conclusion",
)


class TaskFormatError(ValueError):
    pass


@dataclass(frozen=True)
class ExpectedOutput:
    fields: tuple[str, ...]
    findings: tuple[str, ...]


@dataclass(frozen=True)
class Task:
    task_id: str
    workflow: str
    household_id: str
    cutoff: date
    prompt: str
    fixtures: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    expected_output: ExpectedOutput
    grader: str
    justified_conclusion: str
    sha256: str
    grader_params: dict[str, Any]


def parse_task(raw: dict[str, Any], digest: str, source: str) -> Task:
    missing = [f for f in TASK_FIELDS if f not in raw]
    if missing:
        raise TaskFormatError(f"{source}: a task file needs {', '.join(missing)}")
    workflow = str(raw["workflow"])
    if workflow not in WORKFLOWS:
        raise TaskFormatError(f"{source}: workflow {workflow!r} is not one of {WORKFLOWS}")
    fixtures = tuple(str(f) for f in raw["fixtures"])
    if not fixtures or not set(fixtures) <= set(SOURCE_SETS):
        raise TaskFormatError(f"{source}: fixtures are source sets, some of {SOURCE_SETS}")
    cutoff = raw["cutoff"]
    expected = raw["expected_output"]
    if workflow == "compliance":
        problems = compliance_schema_problems(str(f) for f in expected["fields"])
        problems += compliance_prompt_problems(str(raw["prompt"]))
        if problems:
            raise TaskFormatError(f"{source}: a compliance task's {'; '.join(problems)}")
    return Task(
        task_id=str(raw["task_id"]),
        workflow=workflow,
        household_id=str(raw["household_id"]),
        cutoff=cutoff if isinstance(cutoff, date) else parse_date(str(cutoff)),
        prompt=str(raw["prompt"]).strip(),
        fixtures=fixtures,
        allowed_tools=tuple(str(t) for t in raw["allowed_tools"]),
        expected_output=ExpectedOutput(
            fields=tuple(str(f) for f in expected["fields"]),
            findings=tuple(str(f) for f in expected["findings"]),
        ),
        grader=str(raw["grader"]),
        justified_conclusion=str(raw["justified_conclusion"]).strip(),
        sha256=digest,
        grader_params=dict(raw.get("grader_params", {})),
    )


def load_task(path: Path) -> Task:
    data = path.read_bytes()
    return parse_task(tomllib.loads(data.decode("utf-8")), hashlib.sha256(data).hexdigest(), path.name)


def find_task(tasks_dir: Path, task_id: str) -> Task:
    path = tasks_dir / f"{task_id}.toml"
    if not path.is_file():
        raise TaskFormatError(f"no task {task_id} in {tasks_dir}")
    task = load_task(path)
    if task.task_id != task_id:
        raise TaskFormatError(f"{path.name} holds task {task.task_id}, not {task_id}")
    return task
