"""The concentration and basis grader (T-CMP-01, T-CMP-02): clean controls pass, defective outputs fail, a
fabricated figure zeroes, the three counts are right, and a key altered in one figure fails a clean answer."""

import dataclasses
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.concentration_basis import grade
from casebook.keys.concentration_basis import ConcentrationBasisKey, concentration_basis_key
from casebook.model.files import household_dir

AS_OF, TAX_YEAR = date(2026, 4, 15), 2025
NO_COUNTS = {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 0}


@pytest.fixture(scope="module")
def trap(book: Path) -> tuple[ConcentrationBasisKey, Path]:
    root = book / household_dir("HH-3058")
    return concentration_basis_key(root, AS_OF, TAX_YEAR), root


@pytest.fixture(scope="module")
def twin(book: Path) -> tuple[ConcentrationBasisKey, Path]:
    root = book / household_dir("HH-3462")
    return concentration_basis_key(root, AS_OF, TAX_YEAR), root


TRAP_ISSUES = [
    {
        "issue": "Employer stock above the IPS concentration limit",
        "records": ["SEC-0028", "SYN-30580001", "SYN-30580002"],
        "what_the_records_show": "Bramwell Devices Group is $1,265,646.04 of $3,895,524.87, 32.49%, against 15%.",
        "why_the_reviewer_should_look": "The CRM holds no client-signed exception.",
    },
    {
        "issue": "Released shares still held carry no basis",
        "records": ["L-E-3058-0033", "L-E-3058-0047", "CA-3058-03", "CA-3058-04"],
        "what_the_records_show": "Both lots show $0.00 against $409,176.00 the release confirmations support.",
        "why_the_reviewer_should_look": "A later sale would be reported with the wrong basis.",
    },
    {
        "issue": "2025 sale of released shares reported with no basis",
        "records": ["T-3058-0048", "L-E-3058-0005", "L-E-3058-0019"],
        "what_the_records_show": "The realized lots show $0.00 basis, overstating the gain by $356,768.00.",
        "why_the_reviewer_should_look": "The 1099-B would carry the custodian's basis.",
    },
]


def _trap_answer(**fields: Any) -> str:
    answer: dict[str, Any] = {
        "finding": "issues_found",
        "above_concentration_limit": [
            {"security_id": "SEC-0028", "value": "1,265,646.04", "share_of_household": 32.49}
        ],
        "basis_reliable": False,
        "basis_understated": 409176.00,
        "gain_overstated": "$356,768.00",
        "issues_for_reviewer": TRAP_ISSUES,
        "figures": [
            {
                "label": "Bramwell Devices Group, joint account",
                "value": "825134.04",
                "source": "custodian/positions.csv",
            },
            {"label": "Release price, 20 August 2025", "value": "236.83", "source": "crm/crm.json"},
            {"label": "L-E-3058-0033 basis shown", "value": "0.00", "source": "custodian/tax_lots.csv"},
            {
                "label": "Household total value",
                "value": "3895524.87",
                "source": "custodian/positions.csv",
                "computed": True,
            },
        ],
        "explanation": "The employer stock is above the limit and the custodian booked every release at no cost.",
    }
    answer.update(fields)
    return f"Two issues for review.\n\n```json\n{json.dumps(answer, indent=2)}\n```\n"


def _twin_answer(**fields: Any) -> str:
    answer: dict[str, Any] = {
        "finding": "no_issues",
        "above_concentration_limit": [],
        "basis_reliable": True,
        "basis_understated": 0,
        "gain_overstated": None,
        "issues_for_reviewer": [],
        "figures": [{"label": "Ellisar Search Holdings", "value": "250692.00", "source": "custodian/positions.csv"}],
        "explanation": "Ellisar Search Holdings is 6.64% of the household and every release is booked at its value.",
    }
    answer.update(fields)
    return f"Nothing to raise.\n\n```json\n{json.dumps(answer, indent=2)}\n```\n"


def _earned(output: str, key: ConcentrationBasisKey, fixtures: Path) -> dict[str, int]:
    return {c.name: c.earned for c in grade(output, key, fixtures).breakdown}


def test_a_clean_control_on_the_trap_passes(trap: tuple[ConcentrationBasisKey, Path]) -> None:
    result = grade(_trap_answer(), *trap)
    assert (result.score, result.passed, result.critical_fail) == (100, True, None)
    assert result.counts == NO_COUNTS


def test_a_clean_no_issues_on_the_twin_passes(twin: tuple[ConcentrationBasisKey, Path]) -> None:
    result = grade(_twin_answer(), *twin)
    assert (result.score, result.passed) == (100, True)
    assert result.counts == NO_COUNTS


def test_a_false_alarm_on_the_twin_fails_and_counts(twin: tuple[ConcentrationBasisKey, Path]) -> None:
    """Calling the index fund a concentration: the policy says a fund is not one."""
    output = _twin_answer(
        finding="issues_found",
        above_concentration_limit=[{"security_id": "SEC-0013", "value": "1530702.96", "share_of_household": 40.52}],
    )
    result = grade(output, *twin)
    assert not result.passed
    assert result.counts["false_alarm"] == 1
    assert _earned(output, *twin)["concentration"] == 0


def test_no_issues_on_the_trap_fails(trap: tuple[ConcentrationBasisKey, Path]) -> None:
    output = _trap_answer(finding="no_issues", above_concentration_limit=[], basis_reliable=True)
    assert not grade(output, *trap).passed


def test_a_fund_named_beside_the_stock_fails_the_concentration(trap: tuple[ConcentrationBasisKey, Path]) -> None:
    stock = {"security_id": "SEC-0028", "value": "1265646.04", "share_of_household": 32.49}
    fund = {"security_id": "SEC-0013", "value": "737131.47", "share_of_household": 18.92}
    output = _trap_answer(above_concentration_limit=[stock, fund])
    result = grade(output, *trap)
    assert _earned(output, *trap)["concentration"] == 0
    assert not result.passed


def _trap_json() -> dict[str, Any]:
    return json.loads(_trap_answer().split("```json\n")[1].split("```")[0])


def test_the_amounts_swapped_fail_the_basis(trap: tuple[ConcentrationBasisKey, Path]) -> None:
    output = _trap_answer(basis_understated="356768.00", gain_overstated="409176.00")
    result = grade(output, *trap)
    assert result.critical_fail is None
    assert _earned(output, *trap)["basis"] == 0
    assert not result.passed


def test_a_fabricated_figure_zeroes(trap: tuple[ConcentrationBasisKey, Path]) -> None:
    figures = [{"label": "True basis of the sale", "value": "360000.00", "source": "crm/crm.json", "computed": True}]
    result = grade(_trap_answer(figures=figures), *trap)
    assert result.score == 0
    assert result.critical_fail is not None and "True basis of the sale" in result.critical_fail
    assert len(result.breakdown) == 5


def test_a_price_no_file_holds_zeroes(trap: tuple[ConcentrationBasisKey, Path]) -> None:
    output = _trap_answer(explanation="The August release was priced at $240.00 a share.")
    result = grade(output, *trap)
    assert result.score == 0 and result.critical_fail is not None


def test_a_missing_issues_field_fails(trap: tuple[ConcentrationBasisKey, Path]) -> None:
    answer = _trap_json()
    del answer["issues_for_reviewer"]
    output = f"```json\n{json.dumps(answer)}\n```"
    earned = _earned(output, *trap)
    assert earned["output_parses"] == 0 and earned["issues_named"] == 0
    assert not grade(output, *trap).passed


def test_issues_not_naming_their_lots_lose_the_issue_points(trap: tuple[ConcentrationBasisKey, Path]) -> None:
    issues = [{**issue, "records": ["SYN-30580002"]} for issue in TRAP_ISSUES]
    output = _trap_answer(issues_for_reviewer=issues)
    assert _earned(output, *trap)["issues_named"] == 0
    assert grade(output, *trap).score == 75


def test_an_unresolved_answer_is_an_unnecessary_refusal(trap: tuple[ConcentrationBasisKey, Path]) -> None:
    output = _trap_answer(finding="unresolved", basis_reliable=None)
    result = grade(output, *trap)
    assert not result.passed
    assert result.counts == {**NO_COUNTS, "unnecessary_refusal": 1}


def test_a_key_altered_in_one_figure_fails_the_clean_answer(trap: tuple[ConcentrationBasisKey, Path]) -> None:
    key, root = trap
    first = dataclasses.replace(key.held[0], supported=key.held[0].supported + Decimal("100.00"))
    altered = dataclasses.replace(key, held=(first, *key.held[1:]))
    assert not grade(_trap_answer(), altered, root).passed
    wrong_finding = dataclasses.replace(key, finding="no_issues")
    assert not grade(_trap_answer(), wrong_finding, root).passed


def test_a_key_with_no_concentration_fails_the_clean_answer(trap: tuple[ConcentrationBasisKey, Path]) -> None:
    key, root = trap
    altered = dataclasses.replace(key, ips=dataclasses.replace(key.ips, concentrations=()))
    assert not grade(_trap_answer(), altered, root).passed
