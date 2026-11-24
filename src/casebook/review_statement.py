"""The review statement: the reviewer's dated record of a tax review, its date, the reviewer and the scope
(docs/SPEC.md, Words). It is what moves tax items from unreviewed to reviewed (docs/PLAN.md, the held items' table):
a held task's key and verdict, once its scope names the task; a featured household's filled returns, once its scope
names the household. Every other item stays as it was.

The owner adds it as `book/review_statement.json`; `casebook build` checks it and carries it into the book, so the
site, the case packets, the runner and the release all read the one the book was built under.

On a tax item in scope, the review sentence replaces the notice's sentence on unreviewed work, and the rest of the
notice stays; a filled return in scope carries the reviewed watermark (docs/SPEC.md, Rules, and the texts under the
notice).
"""

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from casebook.notice import NOTICE, UNREVIEWED_SENTENCE
from casebook.tasks.task import HELD_GRADERS, HELD_WORKFLOWS, Task
from casebook.watermark import UNREVIEWED, Marks

REVIEW_STATEMENT = "review_statement.json"
STATEMENT_FIELDS = ("date", "reviewer", "scope")
SCOPE_FIELDS = ("summary", "tasks", "households")
_TASK_ID = re.compile(r"T-[A-Z]+-\d{2}")
_HOUSEHOLD_ID = re.compile(r"HH-\d{4}")


class ReviewStatementError(ValueError):
    pass


@dataclass(frozen=True)
class ReviewStatement:
    """`summary`: the scope in words, as the review sentence gives it; `tasks` and `households`: the task IDs and the
    featured households whose returns it covers."""

    date: date
    reviewer: str
    summary: str
    tasks: frozenset[str]
    households: frozenset[str]

    def covers_task(self, task_id: str) -> bool:
        return task_id in self.tasks

    def covers_return(self, household_id: str) -> bool:
        return household_id in self.households

    @property
    def sentence(self) -> str:
        """The review sentence, verbatim from docs/SPEC.md with the statement's date, reviewer and scope."""
        return (
            f"Tax reviewed on {self.date.isoformat()} by {self.reviewer}, for {self.summary}. Answer keys and workflow "
            "judgments outside that scope have not been independently reviewed by qualified practitioners."
        )

    @property
    def notice(self) -> str:
        """The notice on a tax item in scope: the notice with the review sentence for its sentence on unreviewed
        work."""
        return NOTICE.replace(UNREVIEWED_SENTENCE, self.sentence)

    @property
    def watermark(self) -> str:
        """The reviewed watermark, verbatim from docs/SPEC.md with the statement's date."""
        return f"TAX REVIEWED {self.date.isoformat()} · SYNTHETIC · NOT FOR FILING"

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "reviewer": self.reviewer,
            "scope": {"summary": self.summary, "tasks": sorted(self.tasks), "households": sorted(self.households)},
        }


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewStatementError(f"the review statement names no {what}")
    return " ".join(value.split())


def _ids(value: Any, pattern: re.Pattern[str], what: str) -> frozenset[str]:
    if not isinstance(value, list) or not all(isinstance(i, str) and pattern.fullmatch(i) for i in value):  # pyright: ignore[reportUnknownVariableType]
        raise ReviewStatementError(f"the review statement's scope lists its {what} as a list of IDs")
    return frozenset(str(i) for i in value)  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]


def parse_review_statement(raw: Any) -> ReviewStatement:
    """A statement with exactly a date, a reviewer and a scope; the scope with a summary in words and the tasks and
    households it covers, at least one item in all. Anything less is refused (docs/PLAN.md, slice 17, criterion 3)."""
    if not isinstance(raw, dict):
        raise ReviewStatementError("the review statement is a JSON object with a date, a reviewer and a scope")
    statement: dict[str, Any] = raw  # pyright: ignore[reportUnknownVariableType]
    for field in STATEMENT_FIELDS:
        if statement.get(field) in (None, "", {}, []):
            raise ReviewStatementError(f"the review statement names no {field}")
    if set(statement) != set(STATEMENT_FIELDS):
        raise ReviewStatementError(f"the review statement has exactly {', '.join(STATEMENT_FIELDS)}")
    try:
        day = date.fromisoformat(str(statement["date"]))
    except ValueError as error:
        raise ReviewStatementError(f"the review statement's date {statement['date']!r} is not YYYY-MM-DD") from error
    scope = statement["scope"]
    if not isinstance(scope, dict) or set(scope) != set(SCOPE_FIELDS):  # pyright: ignore[reportUnknownArgumentType]
        raise ReviewStatementError(f"the review statement's scope has exactly {', '.join(SCOPE_FIELDS)}")
    fields: dict[str, Any] = scope  # pyright: ignore[reportUnknownVariableType]
    tasks = _ids(fields["tasks"], _TASK_ID, "tasks")
    households = _ids(fields["households"], _HOUSEHOLD_ID, "households")
    if not tasks and not households:
        raise ReviewStatementError("the review statement's scope names no task and no household")
    summary = _text(fields["summary"], "scope in words")
    return ReviewStatement(day, _text(statement["reviewer"], "reviewer"), summary, tasks, households)


def load_review_statement(path: Path) -> ReviewStatement | None:
    """The statement in `path`, or None where there is none."""
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ReviewStatementError(f"{path.name} is not JSON: {error}") from error
    return parse_review_statement(raw)


def statement_of(book: Path) -> ReviewStatement | None:
    """The review statement a book was built under, or None for a book built before any review."""
    return load_review_statement(book / REVIEW_STATEMENT)


def is_tax_task(task: Task) -> bool:
    """A tax item among the tasks: every tax-lot and RMD task, and any other whose key computes a tax figure
    (`casebook.tasks.task`, HELD_WORKFLOWS and HELD_GRADERS)."""
    return task.workflow in HELD_WORKFLOWS or task.grader in HELD_GRADERS


def is_reviewed(task: Task, statement: ReviewStatement | None) -> bool:
    """A tax task a review statement's scope names."""
    return is_tax_task(task) and statement is not None and statement.covers_task(task.task_id)


def is_held(task: Task, statement: ReviewStatement | None) -> bool:
    """Whether a task's key and verdict wait for the tax review: a tax task, until a review statement's scope names it
    (docs/SPEC.md: their pages show "sources and outputs only, with no verdict and no failure marking, until
    review")."""
    return is_tax_task(task) and not is_reviewed(task, statement)


def notice_for_task(task: Task, statement: ReviewStatement | None) -> str:
    """The notice a task's own files and page carry: the reviewed notice for a tax task in a review's scope."""
    return statement.notice if statement is not None and is_reviewed(task, statement) else NOTICE


def household_of(path: str) -> str:
    """The household a return's path names (`sealed/HH-1234/returns/...`, at any depth or in a zip), or ""."""
    found = _HOUSEHOLD_ID.search(path)
    return found.group(0) if found else ""


def return_marks(household_id: str, statement: ReviewStatement | None) -> Marks:
    """The watermark and the notice on every page of a household's filled returns: the reviewed ones for a household
    a review statement covers, "unreviewed" and the notice for every other."""
    if statement is not None and statement.covers_return(household_id):
        return Marks(statement.watermark, statement.notice)
    return UNREVIEWED
