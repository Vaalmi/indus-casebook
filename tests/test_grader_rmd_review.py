"""The RMD review grader (T-TAX-01 and T-TAX-02): clean controls pass, defective answers fail, the three
counts are right, and the grader fails a clean answer once its key is altered."""

import dataclasses
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.rmd_review import grade
from casebook.keys.rmd import HouseholdRmd, household_rmd
from casebook.model.files import SOURCE_SETS, household_dir
from casebook.tasks.fixtures import load_task_fixtures

CUTOFF = date(2026, 4, 15)
NO_COUNTS = {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 0}
POSITIONS = "custodian/positions.csv"


@pytest.fixture(scope="module")
def trap(book: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[HouseholdRmd, Path]:
    workspace = tmp_path_factory.mktemp("HH-5271")
    load_task_fixtures(book, "HH-5271", SOURCE_SETS, CUTOFF, workspace)
    return household_rmd(book / household_dir("HH-5271")), workspace


@pytest.fixture(scope="module")
def twin(book: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[HouseholdRmd, Path]:
    workspace = tmp_path_factory.mktemp("HH-5814")
    load_task_fixtures(book, "HH-5814", SOURCE_SETS, CUTOFF, workspace)
    return household_rmd(book / household_dir("HH-5814")), workspace


def trap_answer(prose: str = "", **fields: Any) -> str:
    """A correct answer on the trap, HH-5271, with any field replaced."""
    answer: dict[str, Any] = {
        "finding": "rmd_missed",
        "rmds": [
            {"account_id": "SYN-52710002", "rmd": "23535.04"},
            {"account_id": "SYN-52710003", "rmd": "7937.50"},
            {"account_id": "SYN-52710004", "rmd": 12729.96},
        ],
        "missed": [{"account_ids": ["SYN-52710004"], "shortfall": "$12,729.96"}],
        "total_shortfall": "12729.96",
        "figures": [
            {"label": "Teodoro Villanueva born", "value": "1952-03-14", "source": "portfolio/household.json"},
            {"label": "401(k) fund on 2024-12-31", "value": "189848.96", "source": "custodian/positions.csv"},
            {"label": "401(k) cash on 2024-12-31", "value": "7,500.00", "source": "custodian/cash.csv"},
            {
                "label": "401(k) balance on 2024-12-31",
                "value": "337343.96",
                "source": "custodian/positions.csv",
                "computed": True,
            },
            {"label": "Uniform Lifetime factor, age 73", "value": "26.5", "source": "IRS Publication 590-B"},
            {"label": "Distribution from SYN-52710002", "value": "-44202.50", "source": "custodian/transactions.csv"},
        ],
        "explanation": "The IRA distribution covers both IRAs' RMDs, but a 401(k)'s RMD must come from the plan.",
    }
    answer.update(fields)
    return (
        prose
        + "\nThe $44,202.50 from SYN-52710002 covers the IRAs' $31,472.54, but the 401(k) paid nothing toward its "
        + f"$12,729.96.\n\n```json\n{json.dumps(answer, indent=2)}\n```\n"
    )


TWIN_RMDS = [
    {"account_id": "SYN-58140002", "rmd": "21979.13"},
    {"account_id": "SYN-58140003", "rmd": "7350.03"},
    {"account_id": "SYN-58140004", "rmd": "11771.97"},
]


def _twin_output(**fields: Any) -> str:
    answer: dict[str, Any] = {
        "finding": "all_rmds_met",
        "rmds": TWIN_RMDS,
        "missed": [],
        "total_shortfall": 0,
        "figures": [
            {"label": "IRA distribution", "value": "-29329.16", "source": "custodian/transactions.csv"},
            {"label": "401(k) distribution", "value": "-11771.97", "source": "custodian/transactions.csv"},
        ],
        "explanation": "The IRAs' RMDs were taken together from one IRA, and the 401(k)'s from the plan.",
    }
    answer.update(fields)
    return f"Every RMD was met.\n\n```json\n{json.dumps(answer, indent=2)}\n```\n"


def _earned(output: str, key: HouseholdRmd, fixtures: Path) -> dict[str, int]:
    return {c.name: c.earned for c in grade(output, key, fixtures).breakdown}


def test_a_clean_control_on_the_trap_passes(trap: tuple[HouseholdRmd, Path]) -> None:
    result = grade(trap_answer(), *trap)
    assert (result.score, result.critical_fail) == (100, None)
    assert result.passed
    assert result.counts == NO_COUNTS


def test_a_clean_control_on_the_twin_passes(twin: tuple[HouseholdRmd, Path]) -> None:
    result = grade(_twin_output(), *twin)
    assert (result.score, result.critical_fail) == (100, None)
    assert result.counts == NO_COUNTS


def test_missing_the_401k_fails(trap: tuple[HouseholdRmd, Path]) -> None:
    # The trap's lure: the custodian's one distribution "for 2025" looks like the whole year's RMD.
    output = trap_answer(finding="all_rmds_met", missed=[], total_shortfall=0)
    result = grade(output, *trap)
    assert _earned(output, *trap) == {"output_parses": 10, "finding": 0, "missed": 0, "rmds": 25, "total_shortfall": 0}
    assert not result.passed
    assert result.counts == NO_COUNTS


def test_the_right_account_with_a_wrong_shortfall_fails(trap: tuple[HouseholdRmd, Path]) -> None:
    # 23,535.04 is SYN-52710002's RMD, a figure the key holds, so not fabricated; but not the 401(k)'s.
    output = trap_answer(
        missed=[{"account_ids": ["SYN-52710004"], "shortfall": "23535.04"}], total_shortfall="23535.04"
    )
    result = grade(output, *trap)
    assert result.critical_fail is None
    assert _earned(output, *trap)["missed"] == 0
    assert not result.passed


def test_an_rmd_against_the_wrong_account_fails(trap: tuple[HouseholdRmd, Path]) -> None:
    # Naming an IRA as short: IRAs are met together, and they were.
    output = trap_answer(missed=[{"account_ids": ["SYN-52710003"], "shortfall": "12729.96"}])
    assert not grade(output, *trap).passed


def test_a_false_alarm_on_the_twin_is_counted(twin: tuple[HouseholdRmd, Path]) -> None:
    # Treating each IRA on its own: SYN-58140003 paid nothing, but its 7,350.03 was paid from SYN-58140002.
    output = _twin_output(
        finding="rmd_missed", missed=[{"account_id": "SYN-58140003", "shortfall": "7350.03"}], total_shortfall="7350.03"
    )
    result = grade(output, *twin)
    assert not result.passed
    assert result.counts == {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 1}


def test_an_unnecessary_refusal_fails_and_is_counted(trap: tuple[HouseholdRmd, Path]) -> None:
    result = grade(trap_answer(finding="unresolved", missed=[], total_shortfall=None), *trap)
    assert not result.passed
    # The key settles every household it covers (it raises otherwise), so "unresolved" is never correct here.
    assert result.counts == {"correct_unresolved": 0, "unnecessary_refusal": 1, "false_alarm": 0}


@pytest.mark.parametrize(
    "figure",
    [
        {"label": "401(k) balance", "value": "340000.00", "source": "custodian/positions.csv", "computed": True},
        # A price the files do not hold, as a real fund's price would be.
        {"label": "SEC-0013 price on 2024-12-31", "value": "512.40", "source": "custodian/positions.csv"},
        # The 401(k)'s fund valued at that price: 868 x 512.40.
        {"label": "401(k) fund at market", "value": "444763.20", "source": "custodian/positions.csv", "computed": True},
        {"label": "Uniform Lifetime factor", "value": "27.4", "source": "IRS Publication 590-B"},
        {"label": "Balance from the statement", "value": "337343.96", "source": "documents/statement-2024.pdf"},
    ],
    ids=["invented balance", "price absent from the files", "balance at that price", "wrong factor", "no such file"],
)
def test_a_fabricated_figure_scores_zero(trap: tuple[HouseholdRmd, Path], figure: dict[str, Any]) -> None:
    output = trap_answer(figures=[figure])
    result = grade(output, *trap)
    assert result.score == 0
    assert result.critical_fail is not None and figure["label"] in result.critical_fail
    assert sum(_earned(output, *trap).values()) == 100


def test_an_invented_amount_in_the_prose_scores_zero(trap: tuple[HouseholdRmd, Path]) -> None:
    result = grade(trap_answer(prose="The excise tax would be $4,100.00."), *trap)
    assert result.score == 0


def test_the_excise_tax_on_the_shortfall_follows_from_the_files(trap: tuple[HouseholdRmd, Path]) -> None:
    # 25% of 12,729.96 = 3,182.49; 10% = 1,273.00.
    result = grade(trap_answer(prose="The excise tax is $3,182.49, or $1,273.00 if corrected in time."), *trap)
    assert (result.score, result.critical_fail) == (100, None)


@pytest.mark.parametrize("field", ["missed", "rmds"])
def test_an_answer_missing_a_list_fails(trap: tuple[HouseholdRmd, Path], field: str) -> None:
    output = trap_answer().replace(f'"{field}"', '"notes"')
    assert not grade(output, *trap).passed


def test_an_answer_with_no_json_block_scores_zero(trap: tuple[HouseholdRmd, Path]) -> None:
    result = grade("The 401(k) RMD was missed.", *trap)
    assert result.score == 0
    assert not result.passed


def _with_401k(key: HouseholdRmd, **changes: Any) -> HouseholdRmd:
    requirements = tuple(dataclasses.replace(r, **changes) if r.account_type == "401k" else r for r in key.requirements)
    return dataclasses.replace(key, requirements=requirements)


@pytest.mark.parametrize(
    ("changes", "lost"),
    [
        ({"rmd": Decimal("12829.96")}, "missed"),  # the shortfall moved by $100
        ({"taken": Decimal("12729.96")}, "finding"),  # the 401(k) paid in full: no finding
    ],
)
def test_the_grader_fails_a_clean_answer_once_the_key_is_altered(
    trap: tuple[HouseholdRmd, Path], changes: dict[str, Any], lost: str
) -> None:
    key, fixtures = trap
    assert grade(trap_answer(), key, fixtures).passed
    altered = _with_401k(key, **changes)
    result = grade(trap_answer(), altered, fixtures)
    assert not result.passed
    assert _earned(trap_answer(), altered, fixtures)[lost] == 0


def test_an_altered_account_rmd_costs_a_clean_answer_its_working(trap: tuple[HouseholdRmd, Path]) -> None:
    # Each account's RMD is the working, not the finding: the answer loses those points but not the pass.
    key, fixtures = trap
    accounts = tuple(
        dataclasses.replace(a, rmd=a.rmd + 5) if a.account_id == "SYN-52710003" else a for a in key.accounts
    )
    altered = dataclasses.replace(key, accounts=accounts)
    assert _earned(trap_answer(), altered, fixtures)["rmds"] == 0
    assert grade(trap_answer(), altered, fixtures).score == 75


@pytest.mark.parametrize("factor", ["26.5", "26.50", "26.500"])
def test_the_table_factor_passes_in_any_decimal_form(trap: tuple[HouseholdRmd, Path], factor: str) -> None:
    """Reviewers A and B, slice 9 round 1: "26.50" passed the cited-figure check but failed the prose scan."""
    key, workspace = trap
    table = {"label": "Uniform Lifetime factor, age 73", "value": factor, "source": "IRS Publication 590-B"}
    result = grade(trap_answer(figures=[table]), key, workspace)
    assert (result.score, result.critical_fail) == (100, None)


def test_a_balance_cited_as_a_price_is_fabricated(trap: tuple[HouseholdRmd, Path]) -> None:
    """Reviewer B, slice 9 round 1: 337,343.96 is the 401(k)'s balance, a figure the key computes, but no
    file holds it as the fund's price ($21.96). A price is read, never derived: one no file holds fails."""
    key, workspace = trap
    price = {"label": "Bond fund price on 2024-12-31", "value": "337343.96", "source": "custodian/positions.csv"}
    result = grade(trap_answer(figures=[price]), key, workspace)
    assert result.score == 0
    assert result.critical_fail is not None and "Bond fund price" in result.critical_fail
    # The same figure, labelled for what it is, is the key's computed balance and passes.
    balance = {"label": "401(k) balance on 2024-12-31", "value": "337343.96", "source": "custodian/positions.csv"}
    assert grade(trap_answer(figures=[balance]), key, workspace).critical_fail is None
    # The true price, from the files, passes as a price.
    true = {"label": "Bond fund price on 2024-12-31", "value": "21.96", "source": "custodian/positions.csv"}
    assert grade(trap_answer(figures=[true]), key, workspace).critical_fail is None


def test_a_price_in_prose_must_be_in_the_files(trap: tuple[HouseholdRmd, Path]) -> None:
    key, workspace = trap
    result = grade(trap_answer("The bond fund was priced at $337,343.96 on 31 December 2024."), key, workspace)
    assert result.critical_fail is not None and "337,343.96" in result.critical_fail
    assert grade(trap_answer("The bond fund was priced at $21.96 on 31 December 2024."), key, workspace).passed


def test_a_table_factor_written_as_money_is_not_a_factor(trap: tuple[HouseholdRmd, Path]) -> None:
    """Reviewer A, slice 9 round 2: the table exemption accepted any amount equal to a factor."""
    key, workspace = trap
    result = grade(trap_answer("The custodian charged a processing fee of $26.50.", figures=[]), key, workspace)
    assert result.score == 0 and result.critical_fail is not None and "26.50" in result.critical_fail


def test_a_price_written_as_text_must_be_in_the_files(trap: tuple[HouseholdRmd, Path]) -> None:
    """Reviewer B, slice 9 round 2: a price given as text slipped through the key-figure fallback."""
    key, workspace = trap
    price = {"label": "Bond fund price on 2024-12-31", "value": "$337,343.96 per share", "source": POSITIONS}
    result = grade(trap_answer(figures=[price]), key, workspace)
    assert result.score == 0 and result.critical_fail is not None


def test_a_calculation_with_prices_is_not_a_price_claim(trap: tuple[HouseholdRmd, Path]) -> None:
    """Reviewer B, slice 9 round 2: working that mentions prices on the way to a balance is not a price."""
    key, workspace = trap
    output = trap_answer("The plan balance: sum(price \u00d7 units) + cash = $337,343.96.")
    assert grade(output, key, workspace).passed


@pytest.mark.parametrize(
    "claim",
    [
        "The bond fund price: $337,343.96 per share.",  # reviewer B, slice 9 targeted check
        "The bond fund's price=$337,343.96.",
        "The bond fund price was $337,343.96.",
        "The bond fund was priced at $337,343.96.",
    ],
)
def test_a_price_stated_with_any_punctuation_must_be_in_the_files(trap: tuple[HouseholdRmd, Path], claim: str) -> None:
    key, workspace = trap
    result = grade(trap_answer(claim), key, workspace)
    assert result.score == 0 and result.critical_fail is not None
