"""The book-level wash-sale sweep: its key on the whole public book against the hand-worked wash sales, and
the list grader scoring answers to T-TAX-06 against it."""

import dataclasses
import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.household_list import grade
from casebook.keys.wash_sale_sweep import WashSaleSweepKey, wash_sale_sweep_key
from casebook.tasks.fixtures import load_task_fixtures

# Each of the four, worked from its custodian files: the loss on the joint account's sale, the units an
# IRA of a spouse bought back within 30 days, and loss x replaced / sold, rounded to the cent.
WASH_SALES = {
    # 642 sold on 2025-10-03, 360 bought in a Roth IRA 12 days later: 31,896.36 x 360 / 642 = 17,885.81
    "HH-0129": ("T-0129-0035", "T-0129-0037", "31896.36", "17885.81", "14010.55"),
    # 3,192 sold on 2025-10-21, 1,340 bought 13 days later: 35,820.62 x 1,340 / 3,192 = 15,037.48
    "HH-0363": ("T-0363-0035", "T-0363-0037", "35820.62", "15037.48", "20783.14"),
    # 879 sold on 2025-09-04, 390 bought 28 days later: 12,860.65 x 390 / 879 = 5,706.09
    "HH-0780": ("T-0780-0022", "T-0780-0031", "12860.65", "5706.09", "7154.56"),
    # 847 sold on 2025-11-03, 500 bought 16 days later: 53,516.17 x 500 / 847 = 31,591.60
    "HH-9234": ("T-9234-0035", "T-9234-0037", "53516.17", "31591.60", "21924.57"),
}
# Bought back 31 to 41 days after the sale (HH-9571 31, HH-0380 35, HH-0981 37, HH-0847 41), or (HH-0679) an
# RSU release 31 days after it. The public book holds no private pair, so archetype 9's pair 2 (a trap and its
# look-alike) is not here.
LOOK_ALIKES = ("HH-0380", "HH-0679", "HH-0847", "HH-0981", "HH-9571")


@pytest.fixture(scope="module")
def key(full_book: Path) -> WashSaleSweepKey:
    return wash_sale_sweep_key(full_book)


@pytest.fixture(scope="module")
def workspace(full_book: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("t-tax-06")
    load_task_fixtures(full_book, "book", ("custodian", "portfolio"), date(2026, 4, 15), root)
    return root


def test_the_key_finds_the_four_wash_sales_with_their_transactions(key: WashSaleSweepKey) -> None:
    assert len(key.checked) == 88
    assert dict(key.found) == {h: (sale, bought) for h, (sale, bought, *_) in WASH_SALES.items()}
    assert key.unresolved == ()


def test_each_found_household_carries_its_hand_worked_figures(key: WashSaleSweepKey) -> None:
    for household, (_, _, loss, disallowed, allowed) in WASH_SALES.items():
        assert [(f.label, f.value) for f in key.figures[household]] == [
            ("loss reported", Decimal(loss)),
            ("disallowed loss", Decimal(disallowed)),
            ("allowed loss", Decimal(allowed)),
        ]


def test_the_look_alikes_are_cleared(key: WashSaleSweepKey) -> None:
    cleared = key.to_dict()["cleared"]
    assert set(LOOK_ALIKES) <= set(cleared)
    # The 88 households less the four found.
    assert len(cleared) == 84


def _entry(household: str) -> dict[str, Any]:
    sale, bought, _, disallowed, _ = WASH_SALES[household]
    return {
        "household_id": household,
        "sale_transaction_ids": [sale],
        "replacement_transaction_ids": [bought],
        "disallowed_loss": disallowed,
        "explanation": "A spouse's IRA bought the fund back within 30 days of the loss sale.",
    }


def _output(**fields: Any) -> str:
    answer: dict[str, Any] = {
        "finding": "found",
        "households": [_entry(h) for h in WASH_SALES],
        "unresolved": [],
        "figures": [
            {
                "label": "HH-9234 loss on T-9234-0035",
                "value": "-53516.17",
                "source": "households/HH-9234/custodian/realized_lots.csv",
            },
            {
                "label": "HH-9234 disallowed loss",
                "value": "31591.60",
                "source": "households/HH-9234/custodian/realized_lots.csv",
                "computed": True,
            },
        ],
        "explanation": "Four households bought the fund they sold at a loss back in an IRA within 30 days.",
    }
    answer.update(fields)
    return f"```json\n{json.dumps(answer)}\n```\n"


NO_COUNTS = {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 0}


def test_a_clean_answer_passes(key: WashSaleSweepKey, workspace: Path) -> None:
    result = grade(_output(), key, workspace)
    assert (result.score, result.critical_fail, result.counts) == (100, None, NO_COUNTS)


def test_a_missed_household_fails(key: WashSaleSweepKey, workspace: Path) -> None:
    result = grade(_output(households=[_entry(h) for h in WASH_SALES if h != "HH-0780"]), key, workspace)
    assert not result.passed


def test_naming_the_31st_day_twin_is_a_false_alarm(key: WashSaleSweepKey, workspace: Path) -> None:
    twin = {"household_id": "HH-9571", "sale_transaction_ids": ["T-9571-0035"], "explanation": "31 days later."}
    result = grade(_output(households=[*(_entry(h) for h in WASH_SALES), twin]), key, workspace)
    assert not result.passed
    assert result.counts == {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 1}


def test_a_household_named_without_its_replacement_loses_the_evidence(key: WashSaleSweepKey, workspace: Path) -> None:
    entries = [_entry(h) for h in WASH_SALES]
    entries[0]["replacement_transaction_ids"] = []
    result = grade(_output(households=entries), key, workspace)
    assert {c.name: c.earned for c in result.breakdown}["evidence"] == 0


def test_a_blanket_refusal_is_an_unnecessary_refusal(key: WashSaleSweepKey, workspace: Path) -> None:
    result = grade(_output(finding="unresolved", households=[], figures=[]), key, workspace)
    assert not result.passed
    assert result.counts == {"correct_unresolved": 0, "unnecessary_refusal": 1, "false_alarm": 0}


def test_a_price_absent_from_the_files_is_fabricated(key: WashSaleSweepKey, workspace: Path) -> None:
    figure = {
        "label": "SEC-0025 price on 2025-11-19",
        "value": "312.40",
        "source": "households/HH-9234/custodian/transactions.csv",
    }
    result = grade(_output(figures=[figure]), key, workspace)
    assert result.score == 0 and result.critical_fail is not None


def _dropped(key: WashSaleSweepKey) -> WashSaleSweepKey:
    return dataclasses.replace(key, found={h: ids for h, ids in key.found.items() if h != "HH-0363"})


def _added(key: WashSaleSweepKey) -> WashSaleSweepKey:
    return dataclasses.replace(key, found={**key.found, "HH-9571": ("T-9571-0035", "T-9571-0037")})


@pytest.mark.parametrize("change", [_dropped, _added], ids=["a household dropped", "a household added"])
def test_an_altered_key_fails_the_clean_answer(
    key: WashSaleSweepKey, workspace: Path, change: Callable[[WashSaleSweepKey], WashSaleSweepKey]
) -> None:
    assert grade(_output(), key, workspace).passed
    assert not grade(_output(), change(key), workspace).passed


def test_an_altered_transaction_in_the_key_costs_the_clean_answer_its_evidence(
    key: WashSaleSweepKey, workspace: Path
) -> None:
    # The list grader holds the set essential, not the evidence, so the answer keeps 80 points and still passes.
    altered = dataclasses.replace(key, found={**key.found, "HH-0363": ("T-0363-0035", "T-0363-0099")})
    result = grade(_output(), altered, workspace)
    assert {c.name: c.earned for c in result.breakdown}["evidence"] == 0
    assert result.score == 80


def test_an_invented_amount_in_a_household_entry_is_a_fabricated_figure(key: WashSaleSweepKey, workspace: Path) -> None:
    """Reviewers A and B, slice 9 round 1: the list grader read the entries as text and never judged their
    amounts, so a correct list with every disallowed loss invented, as a bare JSON number, scored 100."""
    clean = grade(_output(), key, workspace)
    assert clean.critical_fail is None
    invented = [_entry(h) | {"disallowed_loss": 987654321} for h in WASH_SALES]
    result = grade(_output(households=invented, figures=[]), key, workspace)
    assert result.score == 0
    assert result.critical_fail is not None and "987654321" in result.critical_fail
