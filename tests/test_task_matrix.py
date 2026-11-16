"""Slice 5: the task matrix places every task on a household in the shape the plan sets."""

import dataclasses
import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from casebook.build import ID_LEDGER
from casebook.model.ledger import load_ledger
from casebook.tasks.matrix import (
    MatrixError,
    Placement,
    TaskMatrix,
    load_matrix,
    parse_matrix,
    private_problems,
    public_problems,
)
from casebook.tasks.task import WORKFLOWS, load_task

from .conftest import ROOT

MATRIX = ROOT / "tasks" / "matrix.toml"


def featured(book: Path) -> dict[str, tuple[int, int, str]]:
    households = json.loads((book / "sealed" / "households.json").read_text())["households"]
    return {h["household_id"]: (h["archetype"], h["pair"], h["role"]) for h in households if h["set"] == "featured"}


def test_the_public_matrix_places_24_tasks_six_per_workflow() -> None:
    matrix = load_matrix(MATRIX)
    assert len(matrix.placements) == 24
    for workflow in WORKFLOWS:
        assert len([p for p in matrix.placements if p.workflow == workflow]) == 6


def test_the_public_matrix_meets_the_per_workflow_shape_on_the_built_book(book: Path) -> None:
    assert public_problems(load_matrix(MATRIX), featured(book)) == []


def test_every_written_task_sits_where_the_matrix_and_the_ledger_put_it() -> None:
    placed = {p.task_id: p for p in load_matrix(MATRIX).placements}
    ledger = load_ledger(ID_LEDGER)
    for path in sorted((ROOT / "tasks" / "public").glob("*.toml")):
        task = load_task(path)
        assert (placed[task.task_id].household_id, placed[task.task_id].workflow) == (task.household_id, task.workflow)
        ledger.check_task(task.task_id, task.household_id, task.workflow)


def placement(task_id: str, workflow: str, role: str, household: str, partner: str | None = None) -> Placement:
    return Placement(task_id, workflow, role, "asks", household_id=household, pair_task=partner)


def shaped() -> list[Placement]:
    rows: list[Placement] = []
    for i, workflow in enumerate(WORKFLOWS):
        a, b = f"HH-{i}1", f"HH-{i}2"
        rows += [
            placement(f"T-{i}-1", workflow, "trap", a, f"T-{i}-2"),
            placement(f"T-{i}-2", workflow, "twin", b, f"T-{i}-1"),
            placement(f"T-{i}-3", workflow, "trap", f"HH-{i}3", f"T-{i}-4"),
            placement(f"T-{i}-4", workflow, "twin", f"HH-{i}4", f"T-{i}-3"),
            placement(f"T-{i}-5", workflow, "book", "book"),
            placement(f"T-{i}-6", workflow, "book", "book"),
        ]
    return rows


def households_for_shape() -> dict[str, tuple[int, int, str]]:
    return {
        f"HH-{i}{k}": (i * 2 + (k - 1) // 2 + 1, 1, "trap" if k % 2 else "twin") for i in range(4) for k in (1, 2, 3, 4)
    }


def test_a_well_shaped_matrix_passes() -> None:
    assert public_problems(TaskMatrix("m", tuple(shaped())), households_for_shape()) == []


type Rows = list[Placement]


def drop_last(rows: Rows) -> Rows:
    return rows[:-1]


def place_twice(rows: Rows) -> Rows:
    return [rows[0], rows[0], *rows[1:]]


def trap_on_twin(rows: Rows) -> Rows:
    return [placement("T-0-1", "reconciliation", "trap", "HH-02", "T-0-2"), *rows[1:]]


def wrong_partner(rows: Rows) -> Rows:
    return [placement("T-0-1", "reconciliation", "trap", "HH-01", "T-0-3"), *rows[1:]]


def book_task_on_a_household(rows: Rows) -> Rows:
    return [*rows[:4], placement("T-0-5", "reconciliation", "book", "HH-01"), *rows[5:]]


def unknown_household(rows: Rows) -> Rows:
    return [placement("T-0-1", "reconciliation", "trap", "HH-99", "T-0-2"), *rows[1:]]


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (drop_last, "compliance has"),
        (place_twice, "T-0-1 is placed twice"),
        (trap_on_twin, "which is the twin"),
        (wrong_partner, "is not the matching twin"),
        (book_task_on_a_household, "sits on the book"),
        (unknown_household, "not a featured household"),
    ],
)
def test_a_matrix_off_its_shape_fails(change: Callable[[Rows], Rows], problem: str) -> None:
    problems = public_problems(TaskMatrix("m", tuple(change(shaped()))), households_for_shape())
    assert any(problem in p for p in problems), problems


def test_a_malformed_matrix_is_refused() -> None:
    with pytest.raises(MatrixError, match="malformed"):
        parse_matrix({"tasks": [{"task_id": "T-1"}]}, "m.toml")


PRIVATE = Path(os.environ.get("CASEBOOK_PRIVATE", "/nonexistent")) / "tasks" / "matrix.toml"


@pytest.mark.skipif(not PRIVATE.is_file(), reason="the private matrix lives in $CASEBOOK_PRIVATE, absent here")
def test_the_private_matrix_places_eight_tasks_on_background_pairs() -> None:
    matrix = load_matrix(PRIVATE)
    assert len(matrix.placements) == 8
    assert private_problems(matrix) == []


def test_a_private_task_on_a_featured_pair_fails() -> None:
    rows = (
        Placement("X-1", "reconciliation", "trap", "a", archetype=10, pair=1, pair_task="X-2"),
        Placement("X-2", "reconciliation", "twin", "a", archetype=10, pair=1, pair_task="X-1"),
    )
    assert any("background pair" in p for p in private_problems(TaskMatrix("m", rows)))


def private_rows() -> list[Placement]:
    rows: list[Placement] = []
    for i, workflow in enumerate(WORKFLOWS):
        a = i + 1
        rows += [
            Placement(f"X-{i}-1", workflow, "trap", "asks", archetype=a, pair=2, pair_task=f"X-{i}-2"),
            Placement(f"X-{i}-2", workflow, "twin", "asks", archetype=a, pair=2, pair_task=f"X-{i}-1"),
        ]
    return rows


def test_a_well_shaped_private_matrix_passes() -> None:
    assert private_problems(TaskMatrix("m", tuple(private_rows()))) == []


def test_private_partners_on_different_pairs_fail() -> None:
    # Reviewers A and B, slice 5 round 1: swapping two twins' archetypes kept the counts and the links.
    rows = private_rows()
    rows[1], rows[3] = dataclasses.replace(rows[1], archetype=2), dataclasses.replace(rows[3], archetype=1)
    problems = private_problems(TaskMatrix("m", tuple(rows)))
    assert any("its pair task sits on archetype 2, pair 2" in p for p in problems), problems


@pytest.mark.parametrize(("archetype", "pair"), [(10, 99), (11, 2), (0, 3)])
def test_a_private_task_off_the_book_fails(archetype: int, pair: int) -> None:
    rows = [
        dataclasses.replace(p, archetype=archetype, pair=pair) if p.task_id.startswith("X-0") else p
        for p in private_rows()
    ]
    assert any("not archetype" in p for p in private_problems(TaskMatrix("m", tuple(rows))))
