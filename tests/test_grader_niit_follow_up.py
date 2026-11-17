"""The NIIT follow-up grader (T-MTG-03 and T-MTG-04): clean answers with a clean follow-up pass on the trap and
the twin; the tax found on the twin is a false alarm; planning, follow-up and tone score as set; the shared
critical fails apply; and an altered key fails a clean answer."""

import dataclasses
import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.follow_up import FollowUp
from casebook.graders.niit_follow_up import grade
from casebook.keys.niit import NiitKey, niit_key
from casebook.model.files import SOURCE_SETS, household_dir
from casebook.tasks.fixtures import load_task_fixtures

from .test_grader_backdoor_roth_follow_up import activity, earned, note, run, tone

CUTOFF = date(2026, 4, 15)
NO_COUNTS = {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 0}

type Case = tuple[NiitKey, Path]


def _case(book: Path, household: str, factory: pytest.TempPathFactory) -> Case:
    workspace = factory.mktemp(household)
    load_task_fixtures(book, household, SOURCE_SETS, CUTOFF, workspace)
    return niit_key(book / household_dir(household)), workspace


@pytest.fixture(scope="module")
def trap(book: Path, tmp_path_factory: pytest.TempPathFactory) -> Case:
    return _case(book, "HH-2316", tmp_path_factory)


@pytest.fixture(scope="module")
def twin(book: Path, tmp_path_factory: pytest.TempPathFactory) -> Case:
    return _case(book, "HH-2749", tmp_path_factory)


TRAP_MESSAGE = (
    "Dear Ingrid and Kwame, the December sale of the broad market fund brought your 2025 modified AGI to "
    "$316,922.39, over the $250,000.00 threshold, so about $2,543.05 of net investment income tax is due with "
    "your return. Your preparer will confirm it. We would like to talk about holding the bond fund in your IRAs."
)
TWIN_MESSAGE = (
    "Dear Samira and Patrick, your 2025 modified AGI of $238,610.68 stays under the $250,000.00 threshold, so "
    "no net investment income tax is due. We would like to talk about holding the bond fund in your IRAs."
)


def trap_run(*extra: Any) -> FollowUp:
    return run(
        "HH-2316",
        note("HH-2316", 1, "Year-end call: modified AGI $316,922.39, NIIT $2,543.05 from the December sale."),
        activity("HH-2316", 2, "Propose moving the bond fund SEC-0018 into the IRAs."),
        *extra,
    )


def twin_run() -> FollowUp:
    return run(
        "HH-2749",
        note("HH-2749", 1, "Year-end call: modified AGI $238,610.68, under the threshold; no NIIT."),
        activity("HH-2749", 2, "Propose moving the bond fund SEC-0018 into the IRAs."),
    )


def _output(**fields: Any) -> str:
    """A correct answer on the trap, HH-2316, with any field replaced."""
    answer: dict[str, Any] = {
        "finding": "niit_owed",
        "niit": "2,543.05",
        "modified_agi": "316922.39",
        "salt_limit": "$40,000.00",
        "asset_location": ["SEC-0018"],
        "figures": [
            {"label": "Wages, Ingrid", "value": "141,500.00", "source": "documents/P-2316-1-W2-1-2025.pdf"},
            {"label": "Wages, Kwame", "value": "87,000.00", "source": "documents/P-2316-2-W2-1-2025.pdf"},
            {"label": "Dividends", "value": "13,483.67", "source": "documents/SYN-23160001-1099-2025.pdf"},
            {"label": "Gain on T-2316-0035", "value": "74938.72", "source": "custodian/realized_lots.csv"},
            {"label": "Net investment income", "value": "88422.39", "source": "custodian/realized_lots.csv"},
            {"label": "Over the threshold", "value": "66922.39", "source": "custodian/realized_lots.csv"},
        ],
        "explanation": "The December sale's gain put modified AGI over the threshold; the tax is 3.8% of the excess.",
        "client_message": TRAP_MESSAGE,
    }
    answer.update(fields)
    return f"The tax is $2,543.05.\n\n```json\n{json.dumps(answer, indent=2)}\n```\n"


def _twin_output(**fields: Any) -> str:
    answer: dict[str, Any] = {
        "finding": "no_niit",
        "niit": 0,
        "modified_agi": "238,610.68",
        "salt_limit": 40000,
        "asset_location": ["SEC-0018"],
        "figures": [
            {"label": "Dividends", "value": "13,407.79", "source": "documents/SYN-27490001-1099-2025.pdf"},
            {"label": "Under the threshold by", "value": "11389.32", "source": "custodian/realized_lots.csv"},
        ],
        "explanation": "Wages, dividends and the small gain leave modified AGI under the threshold.",
        "client_message": TWIN_MESSAGE,
    }
    answer.update(fields)
    return f"No NIIT.\n\n```json\n{json.dumps(answer, indent=2)}\n```\n"


def test_a_clean_answer_with_a_clean_follow_up_passes_on_the_trap(trap: Case) -> None:
    result = grade(_output(), *trap, trap_run())
    assert (result.score, result.critical_fail, result.passed) == (100, None, True)
    assert result.counts == NO_COUNTS
    assert earned(result) == {
        "output_parses": 10,
        "finding": 20,
        "niit": 15,
        "modified_agi": 10,
        "planning": 10,
        "follow_up": 20,
        "tone": 15,
    }


def test_a_clean_answer_with_a_clean_follow_up_passes_on_the_twin(twin: Case) -> None:
    result = grade(_twin_output(), *twin, twin_run())
    assert (result.score, result.critical_fail, result.passed) == (100, None, True)
    assert result.counts == NO_COUNTS


def test_the_tax_found_on_the_twin_fails_and_counts_a_false_alarm(twin: Case) -> None:
    result = grade(_twin_output(finding="niit_owed", niit="407.21"), *twin, twin_run())
    # 407.21 is in no file and follows from nothing the key computes: a made-up tax is also a fabrication.
    assert not result.passed
    assert result.counts == {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 1}


def test_missing_the_threshold_on_the_trap_fails(trap: Case) -> None:
    # The lure: wages alone, $228,500.00, are under the threshold.
    result = grade(_output(finding="no_niit", niit=0), *trap, trap_run())
    assert not result.passed
    assert (earned(result)["finding"], earned(result)["niit"]) == (0, 0)


@pytest.mark.parametrize(
    "fields",
    [{"salt_limit": "10000.00"}, {"asset_location": []}, {"asset_location": ["SEC-0018", "SEC-0019"]}],
    ids=["the old $10,000 cap", "no asset location", "an equity fund named"],
)
def test_a_planning_slip_loses_its_points_only(trap: Case, fields: dict[str, Any]) -> None:
    result = grade(_output(**fields), *trap, trap_run())
    assert earned(result)["planning"] == 0
    assert result.score == 90 and result.passed


def test_asset_location_that_is_not_a_list_fails_output_parses(trap: Case) -> None:
    result = grade(_output(asset_location="SEC-0018"), *trap, trap_run())
    assert earned(result)["output_parses"] == 0 and earned(result)["planning"] == 0


def test_a_write_to_another_household_scores_zero_and_keeps_the_breakdown(trap: Case) -> None:
    result = grade(_output(), *trap, trap_run(activity("HH-2749", 1, "Call about the bond fund.")))
    assert result.score == 0
    assert result.critical_fail is not None and "HH-2749" in result.critical_fail
    assert earned(result)["niit"] == 15


def test_an_account_number_in_the_client_message_scores_zero(trap: Case) -> None:
    message = TRAP_MESSAGE + " The bond fund sits in SYN-23160001."
    result = grade(_output(client_message=message), *trap, trap_run())
    assert result.score == 0
    assert result.critical_fail is not None and "SYN-23160001" in result.critical_fail


def test_a_note_without_the_tax_loses_the_follow_up_points(trap: Case) -> None:
    follow_up = run("HH-2316", note("HH-2316", 1, "Year-end call held."), activity("HH-2316", 2, "Bond fund."))
    result = grade(_output(), *trap, follow_up)
    assert earned(result)["follow_up"] == 0 and result.score == 80


def test_a_missing_vote_fails_the_grade(trap: Case) -> None:
    follow_up = dataclasses.replace(trap_run(), tone=tone(None, 4, 4))
    result = grade(_output(), *trap, follow_up)
    assert (result.score, result.passed) == (85, False)


def test_a_fabricated_figure_in_a_crm_note_scores_zero(trap: Case) -> None:
    result = grade(_output(), *trap, trap_run(note("HH-2316", 3, "Estimated state tax of $18,250.40.")))
    assert result.score == 0
    assert result.critical_fail is not None and "CRM" in result.critical_fail


def _finding_altered(key: NiitKey) -> NiitKey:
    return dataclasses.replace(key, finding="no_niit")


def _wages_altered(key: NiitKey) -> NiitKey:
    (person, wages), *rest = key.wages
    return dataclasses.replace(key, wages=((person, wages - Decimal("20000.00")), *rest))


@pytest.mark.parametrize(
    "altered", [_finding_altered, _wages_altered], ids=["finding", "wages, so modified AGI and the tax"]
)
def test_an_altered_key_fails_a_clean_answer(trap: Case, altered: Callable[[NiitKey], NiitKey]) -> None:
    key, fixtures = trap
    assert grade(_output(), key, fixtures, trap_run()).passed
    assert not grade(_output(), altered(key), fixtures, trap_run()).passed
