"""The task matrix: which task sits on which household (docs/PLAN.md, New names).

The public matrix places the 24 public tasks: in each workflow two trap-and-twin task pairs on
featured pairs and two book-level tasks. The private matrix, in `$CASEBOOK_PRIVATE`, places the
8 private tasks: in each workflow one trap-and-twin task pair on a background pair, named by its
archetype and pair number until slice 6 gives background households their IDs.
"""

import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from casebook.model.archetypes import ARCHETYPES
from casebook.tasks.task import WORKFLOWS

ROLES = ("trap", "twin", "book")
BOOK = "book"
PUBLIC_SHAPE = {"trap": 2, "twin": 2, "book": 2}
PRIVATE_SHAPE = {"trap": 1, "twin": 1}
FEATURED_PAIR = 1
# Five pairs per archetype: pair 1 is featured, pairs 2 to 5 background (docs/SPEC.md, The book).
BACKGROUND_PAIRS = range(2, 6)


class MatrixError(ValueError):
    pass


@dataclass(frozen=True)
class Placement:
    task_id: str
    workflow: str
    role: str
    asks: str
    household_id: str | None = None
    archetype: int | None = None
    pair: int | None = None
    pair_task: str | None = None


@dataclass(frozen=True)
class TaskMatrix:
    source: str
    placements: tuple[Placement, ...]


def parse_matrix(raw: dict[str, Any], source: str) -> TaskMatrix:
    try:
        placements = tuple(
            Placement(
                task_id=str(t["task_id"]),
                workflow=str(t["workflow"]),
                role=str(t["role"]),
                asks=str(t["asks"]),
                household_id=str(t["household_id"]) if "household_id" in t else None,
                archetype=int(t["archetype"]) if "archetype" in t else None,
                pair=int(t["pair"]) if "pair" in t else None,
                pair_task=str(t["pair_task"]) if "pair_task" in t else None,
            )
            for t in raw["tasks"]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise MatrixError(f"{source}: malformed ({error!r})") from error
    return TaskMatrix(source, placements)


def load_matrix(path: Path) -> TaskMatrix:
    with path.open("rb") as handle:
        return parse_matrix(tomllib.load(handle), path.name)


def _common_problems(matrix: TaskMatrix, shape: dict[str, int]) -> list[str]:
    problems: list[str] = []
    ids = Counter(p.task_id for p in matrix.placements)
    problems += [f"{task} is placed twice" for task, n in sorted(ids.items()) if n > 1]
    for p in matrix.placements:
        if p.workflow not in WORKFLOWS:
            problems.append(f"{p.task_id}: workflow {p.workflow!r} is not one of {WORKFLOWS}")
        if p.role not in ROLES:
            problems.append(f"{p.task_id}: role {p.role!r} is not one of {ROLES}")
    for workflow in WORKFLOWS:
        roles = Counter(p.role for p in matrix.placements if p.workflow == workflow)
        if dict(roles) != shape:
            problems.append(f"{workflow} has {dict(sorted(roles.items()))}, not {shape}")
    by_id = {p.task_id: p for p in matrix.placements}
    for p in matrix.placements:
        if p.role == BOOK:
            continue
        partner = by_id.get(p.pair_task or "")
        want = "twin" if p.role == "trap" else "trap"
        if partner is None or partner.role != want or partner.pair_task != p.task_id or partner.workflow != p.workflow:
            problems.append(f"{p.task_id}: its pair task {p.pair_task} is not the matching {want} task")
    return problems


def public_problems(matrix: TaskMatrix, households: dict[str, tuple[int, int, str]]) -> list[str]:
    """`households`: featured household ID to (archetype, pair, role), from the built book."""
    problems = _common_problems(matrix, PUBLIC_SHAPE)
    by_id = {p.task_id: p for p in matrix.placements}
    for p in matrix.placements:
        if p.role == BOOK:
            if p.household_id != BOOK:
                problems.append(f"{p.task_id}: a book-level task sits on the book, not {p.household_id}")
            continue
        placed = households.get(p.household_id or "")
        if placed is None:
            problems.append(f"{p.task_id}: {p.household_id} is not a featured household of the book")
            continue
        if placed[2] != p.role:
            problems.append(f"{p.task_id}: a {p.role} task sits on {p.household_id}, which is the {placed[2]}")
        partner = by_id.get(p.pair_task or "")
        other = households.get(partner.household_id or "") if partner else None
        if other is not None and other[:2] != placed[:2]:
            problems.append(f"{p.task_id}: its pair task sits on another pair")
    pairs = Counter(households[p.household_id][:2] for p in matrix.placements if p.household_id in households)
    problems += [f"archetype {a}, pair {n} carries {c} tasks, not 2" for (a, n), c in sorted(pairs.items()) if c != 2]
    return problems


def private_problems(matrix: TaskMatrix) -> list[str]:
    problems = _common_problems(matrix, PRIVATE_SHAPE)
    by_id = {p.task_id: p for p in matrix.placements}
    slots: Counter[tuple[int, int]] = Counter()
    for p in matrix.placements:
        if p.archetype is None or p.pair is None or p.archetype not in ARCHETYPES or p.pair not in BACKGROUND_PAIRS:
            problems.append(
                f"{p.task_id}: a private task sits on a background pair (archetype 1 to 10, pair 2 to 5), "
                f"not archetype {p.archetype}, pair {p.pair}"
            )
            continue
        slots[(p.archetype, p.pair)] += 1
        partner = by_id.get(p.pair_task or "")
        if partner is not None and (partner.archetype, partner.pair) != (p.archetype, p.pair):
            problems.append(f"{p.task_id}: its pair task sits on archetype {partner.archetype}, pair {partner.pair}")
    problems += [f"archetype {a}, pair {n} carries {c} tasks, not 2" for (a, n), c in sorted(slots.items()) if c != 2]
    return problems
