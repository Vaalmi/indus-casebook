"""T-REC-02, the near-miss twin's fee task: the same question as T-REC-01 on HH-7350, where billing the
daughter's account apart is correct."""

import dataclasses
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.fee_reconciliation import grade
from casebook.keys.fee_reconciliation import FeeKey, fee_key
from casebook.model.files import household_dir
from casebook.tasks.fixtures import load_task_fixtures
from casebook.tasks.task import load_task

from .conftest import ROOT

TASKS = ROOT / "tasks" / "public"
QUARTER_END = date(2026, 3, 31)
TWIN = "HH-7350"


def test_the_twin_task_asks_the_trap_task_s_question_on_the_twin() -> None:
    trap, twin = load_task(TASKS / "T-REC-01.toml"), load_task(TASKS / "T-REC-02.toml")
    assert (twin.task_id, twin.household_id, twin.workflow) == ("T-REC-02", TWIN, "reconciliation")
    for same in ("cutoff", "prompt", "fixtures", "allowed_tools", "expected_output", "grader", "grader_params"):
        assert getattr(twin, same) == getattr(trap, same), same


def test_the_key_finds_the_twin_billed_correctly(book: Path) -> None:
    key = fee_key(book / household_dir(TWIN), QUARTER_END)
    # Worked by hand from the seed-2026 files, 31 March 2026. The joint account holds 306,140.25 + 129,701.04
    # + 213,282.60 + 149,418.28 = 798,542.17 and 24,830.78 cash: 823,372.95. Kenji's IRA 203,908.80 +
    # 194,573.60 = 398,482.40 and 5,207.05 cash: 403,689.45. Their group BG-7350-1, 1,227,062.40:
    # (10,000 + 0.8% x 227,062.40) / 4 = 2,954.12, debited 1,982.25 + 971.87. Aiko's account 250,453.20 +
    # 151,542.90 + 124,434.00 = 526,430.10 and 10,780.26 cash: 537,210.36, billed on its own under
    # AGR-7350-2: 1% x 537,210.36 / 4 = 1,343.03, debited 1,343.03. No householding agreement joins them.
    assert key.finding == "no_fee_error"
    assert (key.debited_fee, key.correct_fee, key.amount_misbilled) == (
        Decimal("4297.15"),
        Decimal("4297.15"),
        Decimal("0.00"),
    )
    assert [(g.account_ids, g.value, g.fee) for g in key.billing_groups] == [
        (("SYN-73500001", "SYN-73500002"), Decimal("1227062.40"), Decimal("2954.12")),
        (("SYN-73500003",), Decimal("537210.36"), Decimal("1343.03")),
    ]


@pytest.fixture(scope="module")
def workspace(book: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    task = load_task(TASKS / "T-REC-02.toml")
    folder = tmp_path_factory.mktemp("rec02")
    load_task_fixtures(book, task.household_id, task.fixtures, task.cutoff, folder)
    return folder


@pytest.fixture(scope="module")
def key(book: Path) -> FeeKey:
    return fee_key(book / household_dir(TWIN), QUARTER_END)


def _output(**fields: Any) -> str:
    answer: dict[str, Any] = {
        "finding": "no_fee_error",
        "debited_fee": "4,297.15",
        "correct_fee": "4,297.15",
        "amount_misbilled": "0.00",
        "figures": [
            {"label": "Fee debited, joint account", "value": "-1982.25", "source": "custodian/transactions.csv"},
            {"label": "Fee debited, Aiko's account", "value": "-1343.03", "source": "custodian/transactions.csv"},
            {"label": "Aiko's agreement signed", "value": "2020-02-03", "source": "crm/crm.json"},
            {
                "label": "BG-7350-1 value on 2026-03-31",
                "value": "1,227,062.40",
                "source": "custodian/positions.csv",
                "computed": True,
            },
        ],
        "explanation": "Aiko's account is billed on its own under her own agreement; no householding agreement.",
    }
    answer.update(fields)
    return f"The fees were right.\n\n```json\n{json.dumps(answer, indent=2)}\n```\n"


NO_COUNTS = {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 0}


def test_a_clean_no_fee_error_answer_passes(key: FeeKey, workspace: Path) -> None:
    result = grade(_output(), key, workspace)
    assert (result.score, result.critical_fail, result.passed) == (100, None, True)
    assert result.counts == NO_COUNTS


def test_a_fee_error_answer_is_a_false_alarm(key: FeeKey, workspace: Path) -> None:
    # Billing the three accounts as one group (1,764,272.76) would give (10,000 + 0.8% x 764,272.76) / 4 =
    # 4,028.55: a missed breakpoint that is not there. 4,028.55 and 268.60 follow from no agreement in the files.
    output = _output(finding="fee_error", correct_fee="4,028.55", amount_misbilled="268.60", figures=[])
    result = grade(output, key, workspace)
    assert not result.passed
    assert result.counts == {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 1}
    assert {c.name: c.earned for c in result.breakdown}["finding"] == 0


def test_an_unnecessary_refusal_on_the_twin_is_counted(key: FeeKey, workspace: Path) -> None:
    output = _output(finding="unresolved", correct_fee=None, amount_misbilled=None, figures=[])
    result = grade(output, key, workspace)
    assert not result.passed
    assert result.counts == {"correct_unresolved": 0, "unnecessary_refusal": 1, "false_alarm": 0}


@pytest.mark.parametrize(
    "change",
    [
        {"finding": "fee_error"},
        {"correct_fee": Decimal("4028.55"), "amount_misbilled": Decimal("268.60"), "finding": "fee_error"},
    ],
    ids=["the finding", "the correct fee"],
)
def test_an_altered_key_fails_the_clean_answer(key: FeeKey, workspace: Path, change: dict[str, Any]) -> None:
    result = grade(_output(), dataclasses.replace(key, **change), workspace)
    assert {c.name: c.earned for c in result.breakdown}["finding"] == 0
    assert not result.passed


def test_an_altered_debited_fee_marks_the_clean_answer_down(key: FeeKey, workspace: Path) -> None:
    # The fees are not essential to the twin's answer (the finding and the amount are): they cost their 20 points.
    result = grade(_output(), dataclasses.replace(key, debited_fee=Decimal("4397.15")), workspace)
    assert {c.name: c.earned for c in result.breakdown}["fees"] == 0
    assert result.score == 80
