"""The loss-harvesting review grader, on archetype 9's featured pair: clean controls pass, a false alarm on the
near miss fails and counts, defective outputs fail, a fabricated figure zeroes, and an altered key fails a clean
answer."""

import dataclasses
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.loss_harvesting_review import grade
from casebook.keys.loss_harvesting import LossHarvestingKey, loss_harvesting_key
from casebook.model.files import household_dir

NO_COUNTS = {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 0}


@pytest.fixture(scope="module")
def trap(book: Path) -> tuple[LossHarvestingKey, Path]:
    root = book / household_dir("HH-9234")
    return loss_harvesting_key(root), root


@pytest.fixture(scope="module")
def twin(book: Path) -> tuple[LossHarvestingKey, Path]:
    root = book / household_dir("HH-9571")
    return loss_harvesting_key(root), root


WASH_ISSUE = {
    "issue": "Loss sale replaced in the spouse's IRA",
    "records": ["T-9234-0035", "T-9234-0037", "SYN-92340002"],
    "what_the_records_show": "The joint account sold 847 units at a loss; the IRA bought 500 units 16 days later.",
    "why_the_reviewer_should_look": "The custodian reports the whole $53,516.17 loss; $31,591.60 is not allowed.",
}


def _output(answer: dict[str, Any]) -> str:
    return f"For the CCO.\n\n```json\n{json.dumps(answer, indent=2)}\n```\n"


def trap_answer(**fields: Any) -> str:
    answer: dict[str, Any] = {
        "finding": "issues_found",
        "loss_reported": "-53,516.17",
        "disallowed_loss": 31591.60,
        "allowed_loss": "$21,924.57",
        "issues_for_reviewer": [WASH_ISSUE],
        "figures": [
            {"label": "Basis of the units sold", "value": "278072.81", "source": "custodian/realized_lots.csv"},
            {"label": "Proceeds", "value": "224556.64", "source": "custodian/realized_lots.csv"},
            {"label": "Units bought by the IRA", "value": "500", "source": "custodian/transactions.csv"},
            {
                "label": "Days from sale to purchase",
                "value": "16",
                "source": "custodian/transactions.csv",
                "computed": True,
            },
            {
                "label": "Disallowed loss",
                "value": "31591.60",
                "source": "custodian/realized_lots.csv",
                "computed": True,
            },
        ],
        "explanation": "The IRA bought 500 of the 847 units back within 30 days, so their share of the loss is lost.",
    }
    return _output(answer | fields)


def twin_answer(**fields: Any) -> str:
    answer: dict[str, Any] = {
        "finding": "no_issues",
        "loss_reported": "46708.51",
        "disallowed_loss": 0,
        "allowed_loss": "46708.51",
        "issues_for_reviewer": [],
        "figures": [{"label": "Loss on T-9571-0035", "value": "-46708.51", "source": "custodian/realized_lots.csv"}],
        "explanation": "The IRA bought the fund back 31 days after the sale, outside the window, so the loss stands.",
    }
    return _output(answer | fields)


def _earned(output: str, key: LossHarvestingKey, fixtures: Path) -> dict[str, int]:
    return {c.name: c.earned for c in grade(output, key, fixtures).breakdown}


def test_a_clean_control_on_the_trap_passes(trap: tuple[LossHarvestingKey, Path]) -> None:
    result = grade(trap_answer(), *trap)
    assert (result.score, result.passed, result.critical_fail) == (100, True, None)
    assert result.counts == NO_COUNTS


def test_a_clean_control_on_the_twin_passes(twin: tuple[LossHarvestingKey, Path]) -> None:
    result = grade(twin_answer(), *twin)
    assert (result.score, result.passed) == (100, True)
    assert result.counts == NO_COUNTS


def test_the_trap_s_finding_on_the_twin_fails_and_counts_a_false_alarm(twin: tuple[LossHarvestingKey, Path]) -> None:
    """The IRA's purchase 31 days later taken as inside the window: the whole loss of the units bought back raised."""
    issue = {**WASH_ISSUE, "records": ["T-9571-0035", "T-9571-0037"]}
    # 46,708.51 x 500 / 812 = 28,761.40 disallowed: a figure no file holds and the key does not derive.
    output = twin_answer(
        finding="issues_found", disallowed_loss="28761.40", allowed_loss="17947.11", issues_for_reviewer=[issue]
    )
    result = grade(output, *twin)
    assert not result.passed and result.critical_fail is not None
    assert result.counts == {**NO_COUNTS, "false_alarm": 1}
    # Raised with no amount, the alarm still fails the finding and counts.
    quiet = twin_answer(finding="issues_found", issues_for_reviewer=[issue])
    assert _earned(quiet, *twin)["finding"] == 0 and not grade(quiet, *twin).passed
    assert grade(quiet, *twin).counts == {**NO_COUNTS, "false_alarm": 1}


def test_no_issues_on_the_trap_fails(trap: tuple[LossHarvestingKey, Path]) -> None:
    output = trap_answer(finding="no_issues", disallowed_loss=0, allowed_loss="53516.17", issues_for_reviewer=[])
    earned = _earned(output, *trap)
    assert (earned["finding"], earned["disallowed"], earned["issues_named"]) == (0, 0, 0)
    assert not grade(output, *trap).passed


def test_a_wrong_disallowed_loss_fails(trap: tuple[LossHarvestingKey, Path]) -> None:
    # The whole loss disallowed, as if every unit sold were replaced: a figure in the files, so not fabricated.
    output = trap_answer(disallowed_loss="53516.17", allowed_loss=0)
    result = grade(output, *trap)
    assert result.critical_fail is None
    assert _earned(output, *trap)["disallowed"] == 0
    assert not result.passed


def test_a_fabricated_figure_zeroes(trap: tuple[LossHarvestingKey, Path]) -> None:
    figures = [{"label": "Loss lost for good", "value": "30000.00", "source": "custodian/realized_lots.csv"}]
    result = grade(trap_answer(figures=figures), *trap)
    assert result.score == 0
    assert result.critical_fail is not None and "Loss lost for good" in result.critical_fail


def test_a_missing_field_fails(trap: tuple[LossHarvestingKey, Path]) -> None:
    output = trap_answer().replace('"disallowed_loss"', '"disallowed"')
    earned = _earned(output, *trap)
    assert earned["output_parses"] == 0 and earned["disallowed"] == 0
    assert not grade(output, *trap).passed
    # A memo for the chief compliance officer with no issues for the reviewer fails too.
    memo = trap_answer().replace('"issues_for_reviewer"', '"issues"')
    assert (grade(memo, *trap).score, grade(memo, *trap).passed) == (65, False)


def test_an_issue_not_naming_its_purchase_loses_the_issue_points(trap: tuple[LossHarvestingKey, Path]) -> None:
    output = trap_answer(issues_for_reviewer=[{**WASH_ISSUE, "records": ["T-9234-0035"]}])
    assert _earned(output, *trap)["issues_named"] == 0
    assert grade(output, *trap).score == 75


def test_unresolved_is_an_unnecessary_refusal(trap: tuple[LossHarvestingKey, Path]) -> None:
    output = trap_answer(finding="unresolved", disallowed_loss=None, allowed_loss=None)
    result = grade(output, *trap)
    assert not result.passed
    assert result.counts == {**NO_COUNTS, "unnecessary_refusal": 1}


def test_a_key_altered_in_one_figure_fails_the_clean_answer(trap: tuple[LossHarvestingKey, Path]) -> None:
    key, root = trap
    altered = dataclasses.replace(
        key, wash_sales=dataclasses.replace(key.wash_sales, disallowed_loss=Decimal("31691.60"))
    )
    assert not grade(trap_answer(), altered, root).passed
