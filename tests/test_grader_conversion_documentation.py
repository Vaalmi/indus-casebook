"""The conversion documentation grader (T-CMP-03, T-CMP-04): clean controls pass, defective outputs fail, a
fabricated figure zeroes, the three counts are right, and a key altered in one figure fails a clean answer."""

import dataclasses
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.conversion_documentation import grade
from casebook.keys.conversion_documentation import ConversionKey, conversion_key
from casebook.model.files import household_dir

NO_COUNTS = {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 0}


@pytest.fixture(scope="module")
def trap(book: Path) -> tuple[ConversionKey, Path]:
    root = book / household_dir("HH-4105")
    return conversion_key(root, 2025), root


@pytest.fixture(scope="module")
def twin(book: Path) -> tuple[ConversionKey, Path]:
    root = book / household_dir("HH-4633")
    return conversion_key(root, 2025), root


def _output(answer: dict[str, Any], **fields: Any) -> str:
    return f"For review.\n\n```json\n{json.dumps({**answer, **fields}, indent=2)}\n```\n"


TRAP = {
    "finding": "documented",
    "converted": "60,000.00",
    "basis_on_file": 38500,
    "taxable_amount": "$54,900.00",
    "issues_for_reviewer": [
        {
            "issue": "Form 1099-R overstates the taxable amount",
            "records": ["SYN-41050002-1099R-7-2025", "CA-4105-01", "T-4105-0028"],
            "what_the_records_show": "Box 2a shows $60,000.00; the 2024 Form 8606 carries $38,500.00 of basis.",
            "why_the_reviewer_should_look": "The return must carry a 2025 Form 8606 reporting $54,900.00.",
        }
    ],
    "figures": [
        {"label": "Converted", "value": "60000.00", "source": "custodian/transactions.csv"},
        {"label": "Basis carried from 2024", "value": "38500.00", "source": "portfolio/tax_profile.json"},
        {
            "label": "IRA value on 31 December 2025",
            "value": "392711.36",
            "source": "custodian/positions.csv",
            "computed": True,
        },
        {"label": "Form 8606 line 10", "value": "0.085", "source": "custodian/positions.csv", "computed": True},
        {"label": "Nontaxable part", "value": "5100.00", "source": "crm/crm.json", "computed": True},
    ],
    "explanation": "The 2024 Form 8606 documents the basis, so the pro-rata rule makes $54,900.00 taxable.",
}
TWIN = {
    "finding": "unresolved",
    "converted": 60000,
    "basis_on_file": None,
    "taxable_amount": None,
    "issues_for_reviewer": [
        {
            "issue": "Basis claimed with no Form 8606",
            "records": ["CA-4633-01", "CA-4633-02"],
            "what_the_records_show": "No Form 8606 is on file, but Beatriz says she made nondeductible contributions.",
            "why_the_reviewer_should_look": "The taxable amount is $60,000.00 only if she has no basis.",
        }
    ],
    "figures": [{"label": "Converted", "value": "60000.00", "source": "custodian/transactions.csv"}],
    "explanation": "No Form 8606 is on file to prove or rule out the basis she describes.",
}


def test_a_clean_control_on_the_trap_passes(trap: tuple[ConversionKey, Path]) -> None:
    result = grade(_output(TRAP), *trap)
    assert (result.score, result.passed, result.critical_fail) == (100, True, None)
    assert result.counts == NO_COUNTS


def test_a_correct_unresolved_on_the_twin_passes_and_counts(twin: tuple[ConversionKey, Path]) -> None:
    result = grade(_output(TWIN), *twin)
    assert (result.score, result.passed) == (100, True)
    assert result.counts == {**NO_COUNTS, "correct_unresolved": 1}


def test_assuming_no_basis_on_the_twin_fails(twin: tuple[ConversionKey, Path]) -> None:
    result = grade(_output(TWIN, finding="documented", basis_on_file=0, taxable_amount=60000), *twin)
    assert not result.passed
    assert result.counts == NO_COUNTS
    assert {c.name: c.earned for c in result.breakdown}["taxable_amount"] == 0


def test_the_1099_r_figure_on_the_trap_fails(trap: tuple[ConversionKey, Path]) -> None:
    """Box 2a's $60,000.00 taken as the taxable amount: the basis on file ignored."""
    result = grade(_output(TRAP, basis_on_file=0, taxable_amount=60000), *trap)
    assert result.critical_fail is None
    assert not result.passed


def test_unresolved_on_the_trap_is_an_unnecessary_refusal(trap: tuple[ConversionKey, Path]) -> None:
    result = grade(_output(TRAP, finding="unresolved", basis_on_file=None, taxable_amount=None), *trap)
    assert not result.passed
    assert result.counts == {**NO_COUNTS, "unnecessary_refusal": 1}


def test_a_fabricated_figure_zeroes(trap: tuple[ConversionKey, Path]) -> None:
    result = grade(_output(TRAP, taxable_amount=51500), *trap)
    assert result.score == 0 and result.critical_fail is not None and "taxable_amount" in result.critical_fail


def test_a_missing_field_fails(twin: tuple[ConversionKey, Path]) -> None:
    answer = {k: v for k, v in TWIN.items() if k != "taxable_amount"}
    result = grade(_output(answer), *twin)
    earned = {c.name: c.earned for c in result.breakdown}
    assert earned["output_parses"] == 0 and earned["taxable_amount"] == 0
    assert not result.passed


def test_an_issue_not_naming_its_records_loses_the_issue_points(twin: tuple[ConversionKey, Path]) -> None:
    issues = [{**TWIN["issues_for_reviewer"][0], "records": ["SYN-46330002"]}]  # type: ignore[index]
    result = grade(_output(TWIN, issues_for_reviewer=issues), *twin)
    assert {c.name: c.earned for c in result.breakdown}["issues_named"] == 0
    assert result.score == 80


def test_a_key_altered_in_one_figure_fails_the_clean_answer(trap: tuple[ConversionKey, Path]) -> None:
    key, root = trap
    assert key.lines is not None
    altered = dataclasses.replace(key, lines=dataclasses.replace(key.lines, line_18=Decimal("55900.00")))
    assert not grade(_output(TRAP), altered, root).passed
    assert not grade(_output(TRAP), dataclasses.replace(key, finding="unresolved"), root).passed
