"""The IRA distributions grader (T-REC-03 and T-REC-04): clean controls pass, defective answers fail, the
three counts are right, and the grader fails a clean answer once its key is altered."""

import dataclasses
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.ira_distributions import grade
from casebook.keys.ira_distributions import IraDistributionsKey, ira_distributions_key
from casebook.model.files import SOURCE_SETS, household_dir
from casebook.tasks.fixtures import load_task_fixtures

CUTOFF = date(2026, 4, 15)
NO_COUNTS = {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 0}

type Case = tuple[IraDistributionsKey, Path]


def _case(book: Path, household: str, factory: pytest.TempPathFactory) -> Case:
    workspace = factory.mktemp(household)
    load_task_fixtures(book, household, SOURCE_SETS, CUTOFF, workspace)
    return ira_distributions_key(book / household_dir(household)), workspace


@pytest.fixture(scope="module")
def trap(book: Path, tmp_path_factory: pytest.TempPathFactory) -> Case:
    return _case(book, "HH-6047", tmp_path_factory)


@pytest.fixture(scope="module")
def twin(book: Path, tmp_path_factory: pytest.TempPathFactory) -> Case:
    return _case(book, "HH-6590", tmp_path_factory)


def _output(prose: str = "", **fields: Any) -> str:
    """A correct answer on the trap, HH-6047, with any field replaced."""
    answer: dict[str, Any] = {
        "finding": "records_disagree",
        "qcd_amount": "12,000.00",
        "custodian_distributions": "21659.73",
        "taxable_distributions": 9659.73,
        "rmd": "$21,659.73",
        "rmd_met": True,
        "figures": [
            {"label": "Charity's acknowledgment", "value": "12000.00", "source": "crm/crm.json"},
            {"label": "Paid to the charity on", "value": "2025-09-15", "source": "crm/crm.json"},
            {"label": "Custodian's record that day", "value": "-12000.00", "source": "custodian/transactions.csv"},
            {"label": "Second distribution", "value": "-9659.73", "source": "custodian/transactions.csv"},
            {
                "label": "IRA balance on 2024-12-31",
                "value": "476514.06",
                "source": "custodian/positions.csv",
                "computed": True,
            },
            {"label": "Uniform Lifetime factor, age 78", "value": "22.0", "source": "IRS Publication 590-B"},
            {
                "label": "1099-R gross distribution",
                "value": "21,659.73",
                "source": "documents/SYN-60470002-1099R-7-2025.pdf",
            },
        ],
        "explanation": "The CRM's acknowledgment shows the 12,000.00 was a QCD; the custodian coded it a distribution.",
    }
    answer.update(fields)
    return (
        prose
        + "\nThe $12,000.00 the custodian recorded on 2025-09-15 as a required minimum distribution went to the "
        + "charity as a QCD, within the $108,000.00 limit.\n\n"
        + f"```json\n{json.dumps(answer, indent=2)}\n```\n"
    )


def _twin_output(**fields: Any) -> str:
    answer: dict[str, Any] = {
        "finding": "records_agree",
        "qcd_amount": "15000.00",
        "custodian_distributions": "24882.45",
        "taxable_distributions": "9882.45",
        "rmd": "24882.45",
        "rmd_met": True,
        "figures": [
            {"label": "QCD", "value": "-15000.00", "source": "custodian/transactions.csv"},
            {"label": "Acknowledged", "value": "15000.00", "source": "crm/crm.json"},
        ],
        "explanation": "The custodian recorded the QCD as one, as the CRM's acknowledgment says, and the RMD was met.",
    }
    answer.update(fields)
    return f"The records agree.\n\n```json\n{json.dumps(answer, indent=2)}\n```\n"


def _earned(output: str, key: IraDistributionsKey, fixtures: Path) -> dict[str, int]:
    return {c.name: c.earned for c in grade(output, key, fixtures).breakdown}


def test_a_clean_control_on_the_trap_passes(trap: Case) -> None:
    result = grade(_output(), *trap)
    assert (result.score, result.critical_fail) == (100, None)
    assert result.passed
    assert result.counts == NO_COUNTS


def test_a_clean_control_on_the_twin_passes(twin: Case) -> None:
    result = grade(_twin_output(), *twin)
    assert (result.score, result.critical_fail) == (100, None)
    assert result.counts == NO_COUNTS


def test_taking_the_custodian_at_its_word_fails(trap: Case) -> None:
    # The trap's lure: the custodian's records agree with themselves, so all 21,659.73 looks taxable.
    output = _output(finding="records_agree", qcd_amount=0, taxable_distributions="21659.73")
    result = grade(output, *trap)
    assert _earned(output, *trap) == {
        "output_parses": 10,
        "finding": 0,
        "qcd_amount": 0,
        "rmd_met": 15,
        "rmd": 15,
        "distributions": 0,
    }
    assert not result.passed
    assert result.counts == NO_COUNTS


def test_the_right_finding_with_the_rmd_called_missed_fails(trap: Case) -> None:
    # Counting only the 9,659.73 coded as an ordinary distribution toward the RMD: it looks short.
    output = _output(rmd_met=False)
    result = grade(output, *trap)
    assert result.score == 85
    assert not result.passed


def test_a_false_alarm_on_the_twin_is_counted(twin: Case) -> None:
    result = grade(_twin_output(finding="records_disagree"), *twin)
    assert not result.passed
    assert result.counts == {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 1}


def test_an_unnecessary_refusal_fails_and_is_counted(trap: Case) -> None:
    result = grade(_output(finding="unresolved", rmd_met=None, qcd_amount=None), *trap)
    assert not result.passed
    assert result.counts == {"correct_unresolved": 0, "unnecessary_refusal": 1, "false_alarm": 0}


@pytest.mark.parametrize(
    "figure",
    [
        {"label": "IRA balance", "value": "480000.00", "source": "custodian/positions.csv", "computed": True},
        # A price the files do not hold, as a real fund's price would be.
        {"label": "SEC-0001 price on 2024-12-31", "value": "588.21", "source": "custodian/positions.csv"},
        {"label": "Uniform Lifetime factor", "value": "25.5", "source": "IRS Publication 590-B"},
        {"label": "Charity's receipt", "value": "12000.00", "source": "crm/receipts.json"},
    ],
    ids=["invented balance", "price absent from the files", "wrong factor", "no such file"],
)
def test_a_fabricated_figure_scores_zero(trap: Case, figure: dict[str, Any]) -> None:
    output = _output(figures=[figure])
    result = grade(output, *trap)
    assert result.score == 0
    assert result.critical_fail is not None and figure["label"] in result.critical_fail
    assert sum(_earned(output, *trap).values()) == 100


def test_an_invented_headline_amount_scores_zero(trap: Case) -> None:
    result = grade(_output(taxable_distributions="9000.00"), *trap)
    assert (
        result.critical_fail == "fabricated figure: taxable_distributions = 9000.00 is in no file and follows from none"
    )


def test_a_missing_finding_fails(trap: Case) -> None:
    output = _output().replace('"finding"', '"verdict"')
    assert not grade(output, *trap).passed


@pytest.mark.parametrize(
    ("changes", "lost"),
    [
        ({"finding": "records_agree"}, "finding"),
        ({"qcd_amount": Decimal("11000.00")}, "qcd_amount"),
        ({"rmd_met": False}, "rmd_met"),
    ],
)
def test_the_grader_fails_a_clean_answer_once_the_key_is_altered(
    trap: Case, changes: dict[str, Any], lost: str
) -> None:
    key, fixtures = trap
    altered = dataclasses.replace(key, **changes)
    assert not grade(_output(), altered, fixtures).passed
    assert _earned(_output(), altered, fixtures)[lost] == 0
