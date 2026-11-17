"""The grader for preparing a meeting on a Roth conversion, on archetype 4's featured pair: clean controls pass,
the trap's answer on the unresolved twin fails, defective outputs fail, a fabricated figure zeroes, the three
counts are right, and an altered key fails a clean answer."""

import dataclasses
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.conversion_meeting_prep import grade
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


def _output(answer: dict[str, Any]) -> str:
    return f"Meeting notes.\n\n```json\n{json.dumps(answer, indent=2)}\n```\n"


TRAP_BRING = [
    {
        "item": "The 2025 Form 1099-R for the IRA",
        "records": ["SYN-41050002-1099R-7-2025"],
        "why": "It reports the whole $60,000.00 as taxable, with the taxable amount not determined.",
    },
    {
        "item": "The 2024 Form 8606",
        "records": ["CA-4105-01"],
        "why": "Its $38,500.00 of basis goes on line 2 of the 2025 Form 8606.",
    },
]


def trap_answer(**fields: Any) -> str:
    answer: dict[str, Any] = {
        "finding": "documented",
        "converted": "60,000.00",
        "basis_on_file": 38500,
        "taxable_amount": "$54,900.00",
        "to_bring": TRAP_BRING,
        "figures": [
            {"label": "Converted", "value": "60000.00", "source": "custodian/transactions.csv"},
            {"label": "Basis carried from 2024", "value": "38500.00", "source": "portfolio/tax_profile.json"},
            {"label": "Form 8606 line 10", "value": "0.085", "source": "custodian/positions.csv", "computed": True},
            {"label": "Nontaxable part", "value": "5100.00", "source": "crm/crm.json", "computed": True},
        ],
        "explanation": "The 2024 Form 8606 documents the basis, so the pro-rata rule makes $54,900.00 taxable.",
    }
    return _output(answer | fields)


def twin_answer(**fields: Any) -> str:
    answer: dict[str, Any] = {
        "finding": "unresolved",
        "converted": 60000,
        "basis_on_file": None,
        "taxable_amount": None,
        "to_bring": [
            {
                "item": "Beatriz's old Forms 8606 or the returns for the years of her nondeductible contributions",
                "records": ["CA-4633-02", "CA-4633-01"],
                "why": "Her 2024 return has no Form 8606, so only those can show the basis she describes.",
            }
        ],
        "figures": [{"label": "Converted", "value": "60000.00", "source": "custodian/transactions.csv"}],
        "explanation": "No Form 8606 is on file to prove or rule out the basis she describes.",
    }
    return _output(answer | fields)


def _earned(output: str, key: ConversionKey, fixtures: Path) -> dict[str, int]:
    return {c.name: c.earned for c in grade(output, key, fixtures).breakdown}


def test_a_clean_control_on_the_trap_passes(trap: tuple[ConversionKey, Path]) -> None:
    result = grade(trap_answer(), *trap)
    assert (result.score, result.passed, result.critical_fail) == (100, True, None)
    assert result.counts == NO_COUNTS


def test_a_correct_unresolved_on_the_twin_passes_and_counts(twin: tuple[ConversionKey, Path]) -> None:
    result = grade(twin_answer(), *twin)
    assert (result.score, result.passed) == (100, True)
    assert result.counts == {**NO_COUNTS, "correct_unresolved": 1}


def test_the_trap_s_answer_on_the_twin_fails(twin: tuple[ConversionKey, Path]) -> None:
    """No basis assumed, so the whole conversion taxed: neither finding is an alarm, so nothing is counted."""
    output = twin_answer(finding="documented", basis_on_file=0, taxable_amount=60000, to_bring=[])
    result = grade(output, *twin)
    assert not result.passed
    assert result.counts == NO_COUNTS
    assert _earned(output, *twin)["taxable_amount"] == 0 and _earned(output, *twin)["to_bring_named"] == 0


def test_the_1099_r_figure_on_the_trap_fails(trap: tuple[ConversionKey, Path]) -> None:
    result = grade(trap_answer(basis_on_file=0, taxable_amount=60000), *trap)
    assert result.critical_fail is None
    assert not result.passed


def test_unresolved_on_the_trap_is_an_unnecessary_refusal(trap: tuple[ConversionKey, Path]) -> None:
    result = grade(trap_answer(finding="unresolved", basis_on_file=None, taxable_amount=None), *trap)
    assert not result.passed
    assert result.counts == {**NO_COUNTS, "unnecessary_refusal": 1}


def test_a_fabricated_figure_zeroes(trap: tuple[ConversionKey, Path]) -> None:
    result = grade(trap_answer(taxable_amount=51500), *trap)
    assert result.score == 0 and result.critical_fail is not None and "taxable_amount" in result.critical_fail


def test_a_missing_field_fails(twin: tuple[ConversionKey, Path]) -> None:
    output = twin_answer().replace('"to_bring"', '"bring"')
    earned = _earned(output, *twin)
    assert earned["output_parses"] == 0 and earned["to_bring_named"] == 0
    result = grade(output, *twin)
    # 70 points, but what to bring is half the question, so a pass cannot do without it.
    assert (result.score, result.passed) == (70, False)


def test_what_to_bring_may_name_its_records_across_entries_but_not_leave_one_out(
    trap: tuple[ConversionKey, Path],
) -> None:
    assert _earned(trap_answer(), *trap)["to_bring_named"] == 20
    output = trap_answer(to_bring=TRAP_BRING[:1])
    assert _earned(output, *trap)["to_bring_named"] == 0
    malformed = trap_answer(to_bring=[{"item": "The Form 1099-R", "records": "SYN-41050002-1099R-7-2025"}])
    assert _earned(malformed, *trap)["output_parses"] == 0


def test_a_key_altered_in_one_figure_fails_the_clean_answer(trap: tuple[ConversionKey, Path]) -> None:
    key, root = trap
    assert key.lines is not None
    altered = dataclasses.replace(key, lines=dataclasses.replace(key.lines, line_18=Decimal("55900.00")))
    assert not grade(trap_answer(), altered, root).passed
    assert not grade(trap_answer(), dataclasses.replace(key, finding="unresolved"), root).passed
