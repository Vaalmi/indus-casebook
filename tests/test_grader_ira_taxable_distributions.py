"""The grader for the taxable part of a household's 2025 IRA distributions, counting any QCD, on archetype 6's
featured pair (HH-6047, whose custodian recorded the QCD as an ordinary distribution; HH-6590, whose custodian
recorded it as one): clean controls pass, the custodian taken at its word fails, a false alarm on the twin
counts, defective answers fail, and an altered key fails a clean answer."""

import dataclasses
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.ira_taxable_distributions import grade
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


def _output(answer: dict[str, Any]) -> str:
    return f"What is taxable.\n\n```json\n{json.dumps(answer, indent=2)}\n```\n"


def trap_answer(**fields: Any) -> str:
    # T-REC-03's justified conclusion: 12,000.00 (T-6047-0016) and 9,659.73 left SYN-60470002; the first was a QCD
    # (CA-6047-01, CA-6047-02), so 21,659.73 - 12,000.00 = 9,659.73 is taxable.
    answer: dict[str, Any] = {
        "finding": "records_disagree",
        "custodian_distributions": "21,659.73",
        "qcd_amount": 12000,
        "taxable_distributions": "$9,659.73",
        "figures": [
            {"label": "Charity's acknowledgment", "value": "12000.00", "source": "crm/crm.json"},
            {"label": "Custodian's record that day", "value": "-12000.00", "source": "custodian/transactions.csv"},
            {"label": "Second distribution", "value": "-9659.73", "source": "custodian/transactions.csv"},
            {"label": "Uniform Lifetime factor, age 78", "value": "22.0", "source": "IRS Publication 590-B"},
        ],
        "explanation": "The custodian coded the QCD as a distribution; only the $9,659.73 is taxable.",
    }
    return _output(answer | fields)


def twin_answer(**fields: Any) -> str:
    answer: dict[str, Any] = {
        "finding": "records_agree",
        "custodian_distributions": "24882.45",
        "qcd_amount": "15000.00",
        "taxable_distributions": "9882.45",
        "figures": [
            {"label": "QCD", "value": "-15000.00", "source": "custodian/transactions.csv"},
            {"label": "Acknowledged", "value": "15000.00", "source": "crm/crm.json"},
        ],
        "explanation": "The custodian recorded the QCD as one, so only the ordinary distribution is taxable.",
    }
    return _output(answer | fields)


def _earned(output: str, case: Case) -> dict[str, int]:
    return {c.name: c.earned for c in grade(output, *case).breakdown}


def test_clean_controls_pass(trap: Case, twin: Case) -> None:
    for output, case in ((trap_answer(), trap), (twin_answer(), twin)):
        result = grade(output, *case)
        assert (result.score, result.passed, result.critical_fail) == (100, True, None)
        assert result.counts == NO_COUNTS


def test_taking_the_custodian_at_its_word_fails(trap: Case) -> None:
    output = trap_answer(finding="records_agree", qcd_amount=0, taxable_distributions="21659.73")
    assert _earned(output, trap) == {
        "output_parses": 10,
        "finding": 0,
        "taxable_distributions": 0,
        "qcd_amount": 0,
        "custodian_distributions": 15,
    }
    assert not grade(output, *trap).passed


def test_the_trap_s_finding_on_the_twin_is_a_false_alarm(twin: Case) -> None:
    result = grade(twin_answer(finding="records_disagree"), *twin)
    assert not result.passed and result.counts == {**NO_COUNTS, "false_alarm": 1}


def test_a_wrong_taxable_amount_fails(twin: Case) -> None:
    # The whole 24,882.45 taken as taxable: in the files, so not fabricated, but the QCD is not excluded.
    output = twin_answer(taxable_distributions="24882.45")
    result = grade(output, *twin)
    assert result.critical_fail is None and _earned(output, twin)["taxable_distributions"] == 0
    assert not result.passed


def test_a_fabricated_figure_zeroes(trap: Case) -> None:
    figures = [{"label": "IRA balance", "value": "470000.00", "source": "custodian/positions.csv"}]
    result = grade(trap_answer(figures=figures), *trap)
    assert result.score == 0 and result.critical_fail is not None and "IRA balance" in result.critical_fail


def test_a_missing_field_fails(trap: Case) -> None:
    output = trap_answer().replace('"qcd_amount"', '"qcd"')
    assert _earned(output, trap)["output_parses"] == 0
    assert not grade(output, *trap).passed


def test_unresolved_is_an_unnecessary_refusal(trap: Case) -> None:
    result = grade(trap_answer(finding="unresolved"), *trap)
    assert not result.passed and result.counts == {**NO_COUNTS, "unnecessary_refusal": 1}


def test_a_key_altered_in_one_figure_fails_the_clean_answer(trap: Case) -> None:
    key, root = trap
    altered = dataclasses.replace(key, taxable_distributions=Decimal("9759.73"))
    assert not grade(trap_answer(), altered, root).passed
