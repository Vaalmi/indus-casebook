"""The ID ledger: what each published household and task ID means (docs/PLAN.md, New names).

Once an ID is published it keeps its meaning: a household its archetype, pair and role, a task
its household and workflow. The file is committed and only grows; the build refuses a household
whose script contradicts its entry.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# A book-level task's household: it reads every household of the book.
BOOK = "book"


class LedgerError(ValueError):
    pass


@dataclass(frozen=True)
class LedgerHousehold:
    archetype: int
    pair: int
    role: str


@dataclass(frozen=True)
class LedgerTask:
    household_id: str
    workflow: str


@dataclass(frozen=True)
class IdLedger:
    households: dict[str, LedgerHousehold]
    tasks: dict[str, LedgerTask]

    def check_household(self, household_id: str, archetype: int, pair: int, role: str) -> None:
        """Refuse a household whose archetype, pair or role differs from its published meaning."""
        entry = self.households.get(household_id)
        if entry is not None and entry != LedgerHousehold(archetype, pair, role):
            raise LedgerError(
                f"{household_id} is published as archetype {entry.archetype}, pair {entry.pair}, {entry.role}; "
                f"the script makes it archetype {archetype}, pair {pair}, {role}. "
                "A published ID keeps its meaning: give the household a new ID instead"
            )

    def check_task(self, task_id: str, household_id: str, workflow: str) -> None:
        entry = self.tasks.get(task_id)
        if entry is not None and entry != LedgerTask(household_id, workflow):
            raise LedgerError(
                f"{task_id} is published as {entry.workflow} on {entry.household_id}; "
                f"its file makes it {workflow} on {household_id}. A published ID keeps its meaning"
            )


def parse_ledger(raw: Any, source: str) -> IdLedger:
    try:
        households = {
            str(hid): LedgerHousehold(int(h["archetype"]), int(h["pair"]), str(h["role"]))
            for hid, h in raw["households"].items()
        }
        tasks = {str(tid): LedgerTask(str(t["household_id"]), str(t["workflow"])) for tid, t in raw["tasks"].items()}
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise LedgerError(f"{source}: malformed ({error!r})") from error
    unknown = sorted(t.household_id for t in tasks.values() if t.household_id not in {*households, BOOK})
    if unknown:
        raise LedgerError(f"{source}: a task names a household the ledger does not hold ({', '.join(unknown)})")
    return IdLedger(households, tasks)


def load_ledger(path: Path) -> IdLedger:
    if not path.is_file():
        raise LedgerError(f"{path}: the ID ledger is missing")
    return parse_ledger(json.loads(path.read_text(encoding="utf-8")), path.as_posix())
