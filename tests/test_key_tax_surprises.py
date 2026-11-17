"""The tax surprises key (T-MTG-06): the whole book's call list by kind of surprise, and the household-list
grader on its key."""

import dataclasses
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.household_list import grade
from casebook.keys.tax_surprises import tax_surprises_key
from casebook.tasks.fixtures import load_task_fixtures
from casebook.tasks.task import BOOK

BACKDOOR = ("HH-0218", "HH-0347", "HH-0690", "HH-0844", "HH-1204")
# T-TAX-05's nine and T-TAX-06's five (tests/test_key_rmd_sweep.py, tests/test_key_wash_sale_sweep.py).
RMD = ("HH-0120", "HH-0236", "HH-0371", "HH-0466", "HH-0491", "HH-0607", "HH-0664", "HH-0842", "HH-5271")
WASH = ("HH-0129", "HH-0363", "HH-0507", "HH-0780", "HH-9234")


@pytest.fixture(scope="module")
def key(full_book: Path) -> Any:
    return tax_surprises_key(full_book)


def test_the_book_has_nineteen_households_to_call_each_for_one_surprise(key: Any) -> None:
    kinds = {h: tuple(s) for h, s in key.surprises.items()}
    assert kinds == {
        **dict.fromkeys(BACKDOOR, ("backdoor_roth_taxed",)),
        **dict.fromkeys(RMD, ("rmd_not_met",)),
        **dict.fromkeys(WASH, ("wash_sale",)),
    }
    assert key.unresolved == ()


def test_a_taxed_backdoor_is_named_by_its_person_and_conversion(key: Any) -> None:
    # HH-1204: Luka, P-1204-2, converted on 2025-02-13 (T-1204-0006); 6,748.00 of it is taxable, worked by hand in
    # tests/test_key_backdoor_roth.py.
    assert key.found["HH-1204"] == ("P-1204-2", "T-1204-0006")
    (backdoor,) = key.backdoors["HH-1204"]
    assert backdoor.taxable == Decimal("6748.00")
    # The look-alikes, whose pre-tax money sits in a 401(k), are not called.
    assert not {"HH-1587", "HH-0608", "HH-0633", "HH-0747", "HH-0799"} & set(key.found)


def _answer(households: list[dict[str, Any]]) -> str:
    answer = {
        "finding": "found",
        "households": households,
        "unresolved": [],
        "figures": [],
        "explanation": "Five backdoor Roths taxed pro rata, nine RMDs not met, five wash sales.",
    }
    return f"```json\n{json.dumps(answer)}\n```\n"


def _entries(key: Any) -> list[dict[str, Any]]:
    return [
        {"household_id": h, "surprises": list(s), "transaction_ids": list(key.found[h]), "explanation": "As listed."}
        for h, s in key.surprises.items()
    ]


def test_the_grader_passes_the_clean_list_and_fails_a_miss_or_a_false_alarm(
    key: Any, full_book: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    workspace = tmp_path_factory.mktemp("book-surprises")
    load_task_fixtures(full_book, BOOK, ("custodian", "portfolio", "crm"), date(2026, 4, 15), workspace)
    entries = _entries(key)
    assert grade(_answer(entries), key, workspace).passed
    without_backdoors = [e for e in entries if e["household_id"] not in BACKDOOR]
    assert not grade(_answer(without_backdoors), key, workspace).passed
    twin = {"household_id": "HH-1587", "surprises": ["backdoor_roth_taxed"], "explanation": "A backdoor Roth."}
    alarm = grade(_answer([*entries, twin]), key, workspace)
    assert not alarm.passed and alarm.counts["false_alarm"] == 1


def test_an_altered_key_fails_the_clean_list(
    key: Any, full_book: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    workspace = tmp_path_factory.mktemp("book-surprises-altered")
    load_task_fixtures(full_book, BOOK, ("custodian", "portfolio", "crm"), date(2026, 4, 15), workspace)
    altered = dataclasses.replace(key, backdoors={h: b for h, b in key.backdoors.items() if h != "HH-1204"})
    assert not grade(_answer(_entries(key)), altered, workspace).passed
