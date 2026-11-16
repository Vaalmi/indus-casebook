"""The household list grader: clean controls pass, defective lists fail, the three counts are per household,
and a fabricated figure zeroes."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.household_list import grade
from casebook.keys.figures import KeyFigure


@dataclass(frozen=True)
class ListKey:
    """A hand-built key in the shape the grader takes."""

    checked: tuple[str, ...]
    found: Mapping[str, tuple[str, ...]]
    unresolved: tuple[str, ...] = ()
    computed_figures: tuple[KeyFigure, ...] = field(default=())


BOOK = ("HH-0001", "HH-0002", "HH-0003", "HH-0004")
# HH-0001 is found: its agreement AGR-0001-2 joins accounts its billing groups BG-0001-1 and BG-0001-2 hold apart.
EVIDENCE = ("AGR-0001-2", "BG-0001-1", "BG-0001-2")
OVERBILLED = (KeyFigure("amount misbilled", Decimal("50.00")),)
KEY = ListKey(BOOK, {"HH-0001": EVIDENCE}, computed_figures=OVERBILLED)
CLEAN_BOOK = ListKey(BOOK, {})
# The files leave HH-0004 unresolved; HH-0001 is found.
WITH_UNRESOLVED = ListKey(BOOK, {"HH-0001": EVIDENCE}, ("HH-0004",), OVERBILLED)
ONLY_UNRESOLVED = ListKey(BOOK, {}, ("HH-0004",))

CRM = "households/HH-0001/crm/crm.json"
PRICES = "households/HH-0001/custodian/positions.csv"


@pytest.fixture
def fixtures(tmp_path: Path) -> Path:
    crm = tmp_path / CRM
    crm.parent.mkdir(parents=True)
    crm.write_text(
        json.dumps({"agreements": [{"agreement_id": "AGR-0001-2", "signed": "2025-06-01"}]}), encoding="utf-8"
    )
    (tmp_path / PRICES).parent.mkdir(parents=True)
    (tmp_path / PRICES).write_text(
        "account_id,security_id,units,price,market_value\nSYN-00010001,SEC-0001,1000,600.00,600000.00\n",
        encoding="utf-8",
    )
    return tmp_path


def _entry(household: str, *evidence: str) -> dict[str, Any]:
    return {
        "household_id": household,
        "agreement_id": evidence[0] if evidence else None,
        "billing_group_ids": list(evidence[1:]),
        "explanation": "The billing groups keep apart the accounts the agreement joins.",
    }


def _output(**fields: Any) -> str:
    answer: dict[str, Any] = {
        "finding": "found",
        "households": [_entry("HH-0001", *EVIDENCE)],
        "unresolved": [],
        "figures": [
            {"label": "AGR-0001-2 signed", "value": "2025-06-01", "source": CRM},
            {"label": "SYN-00010001 value", "value": "600,000.00", "source": PRICES},
            {"label": "Overbilled", "value": "50.00", "source": PRICES, "computed": True},
        ],
        "explanation": "One household's billing groups contradict its householding agreement.",
    }
    answer.update(fields)
    return f"One household.\n\n```json\n{json.dumps(answer, indent=2)}\n```\n"


NONE_FOUND = {"finding": "none_found", "households": [], "unresolved": [], "figures": []}
NO_COUNTS = {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 0}


def _earned(output: str, key: ListKey, fixtures: Path) -> dict[str, int]:
    return {c.name: c.earned for c in grade(output, key, fixtures).breakdown}


def test_a_clean_control_passes(fixtures: Path) -> None:
    result = grade(_output(), KEY, fixtures)
    assert (result.score, result.critical_fail, result.passed) == (100, None, True)
    assert result.counts == NO_COUNTS


def test_a_correct_none_found_on_a_clean_book_passes(fixtures: Path) -> None:
    result = grade(_output(**NONE_FOUND), CLEAN_BOOK, fixtures)
    assert (result.score, result.passed) == (100, True)
    assert result.counts == NO_COUNTS


def test_a_missing_household_fails(fixtures: Path) -> None:
    output = _output(**NONE_FOUND)
    assert _earned(output, KEY, fixtures) == {
        "output_parses": 10,
        "none_missed": 0,
        "none_wrongly_named": 35,
        "evidence": 0,
    }
    result = grade(output, KEY, fixtures)
    assert (result.score, result.passed) == (45, False)
    assert result.counts == NO_COUNTS


def test_a_wrongly_named_household_fails_and_is_a_false_alarm(fixtures: Path) -> None:
    output = _output(households=[_entry("HH-0001", *EVIDENCE), _entry("HH-0002", "AGR-0002-1")])
    assert _earned(output, KEY, fixtures) == {
        "output_parses": 10,
        "none_missed": 35,
        "none_wrongly_named": 0,
        "evidence": 20,
    }
    result = grade(output, KEY, fixtures)
    assert (result.score, result.passed) == (65, False)
    assert result.counts == {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 1}


def test_each_false_alarm_on_a_clean_book_counts(fixtures: Path) -> None:
    # Two cleared households and one the book does not hold: three false alarms.
    named = [_entry("HH-0002"), _entry("HH-0003"), _entry("HH-9999")]
    result = grade(_output(households=named, figures=[]), CLEAN_BOOK, fixtures)
    assert not result.passed
    assert result.counts == {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 3}


def test_a_household_named_without_its_evidence_loses_only_the_evidence(fixtures: Path) -> None:
    output = _output(households=[_entry("HH-0001", "AGR-0001-2", "BG-0001-1")])
    criteria = {c.name: c for c in grade(output, KEY, fixtures).breakdown}
    assert criteria["evidence"].earned == 0
    assert criteria["evidence"].detail == "HH-0001: lacks BG-0001-2"
    assert grade(output, KEY, fixtures).score == 80


def test_a_correct_unresolved_passes_and_is_counted(fixtures: Path) -> None:
    unresolved = [{"household_id": "HH-0004", "explanation": "No valuation on the date."}]
    result = grade(_output(unresolved=unresolved), WITH_UNRESOLVED, fixtures)
    assert (result.score, result.passed) == (100, True)
    assert result.counts == {"correct_unresolved": 1, "unnecessary_refusal": 0, "false_alarm": 0}


def test_leaving_out_a_household_the_key_leaves_unresolved_is_a_miss(fixtures: Path) -> None:
    result = grade(_output(), WITH_UNRESOLVED, fixtures)
    assert next(c for c in result.breakdown if c.name == "none_missed").earned == 0
    assert not result.passed


def test_an_unnecessary_refusal_fails_and_is_counted(fixtures: Path) -> None:
    # HH-0001 is found by the key; the answer calls it unresolved.
    output = _output(finding="unresolved", households=[], unresolved=["HH-0001"], figures=[])
    assert _earned(output, KEY, fixtures) == {
        "output_parses": 10,
        "none_missed": 0,
        "none_wrongly_named": 0,
        "evidence": 0,
    }
    result = grade(output, KEY, fixtures)
    assert result.counts == {"correct_unresolved": 0, "unnecessary_refusal": 1, "false_alarm": 0}


def test_a_blanket_refusal_on_a_book_the_files_settle_fails_and_counts_once(fixtures: Path) -> None:
    output = _output(finding="unresolved", households=[], unresolved=[], figures=[])
    result = grade(output, CLEAN_BOOK, fixtures)
    assert (result.score, result.passed) == (10, False)
    assert result.counts == {"correct_unresolved": 0, "unnecessary_refusal": 1, "false_alarm": 0}


def test_a_blanket_refusal_where_the_key_settles_nothing_is_a_correct_unresolved_that_still_fails(
    fixtures: Path,
) -> None:
    # It names no household, so it misses the one the key leaves unresolved.
    output = _output(finding="unresolved", households=[], unresolved=[], figures=[])
    result = grade(output, ONLY_UNRESOLVED, fixtures)
    assert not result.passed
    assert result.counts == {"correct_unresolved": 1, "unnecessary_refusal": 0, "false_alarm": 0}


@pytest.mark.parametrize(
    "figure",
    [
        {"label": "Householding discount", "value": "1234.56", "source": CRM},
        {"label": "Householding discount", "value": "1234.56", "source": CRM, "computed": True},
        {"label": "Householding discount", "value": "1234.56", "source": "households/HH-0001/crm/notes.json"},
        # A price absent from the files: the custodian prices SEC-0001 at 600.00.
        {"label": "SEC-0001 price", "value": "1,850.00", "source": PRICES},
    ],
    ids=["not in the source", "computed but not by the key", "source missing", "a price absent from the files"],
)
def test_a_fabricated_figure_scores_zero_and_keeps_its_breakdown(fixtures: Path, figure: dict[str, Any]) -> None:
    output = _output(figures=[figure])
    result = grade(output, KEY, fixtures)
    assert (result.score, result.passed) == (0, False)
    assert result.critical_fail is not None and figure["label"] in result.critical_fail
    assert _earned(output, KEY, fixtures) == {
        "output_parses": 10,
        "none_missed": 35,
        "none_wrongly_named": 35,
        "evidence": 20,
    }


def test_an_invented_amount_in_the_prose_is_fabricated(fixtures: Path) -> None:
    result = grade("The household was overbilled by $1,410.05.\n" + _output(), KEY, fixtures)
    assert result.critical_fail is not None and "1,410.05" in result.critical_fail


def test_a_block_missing_a_field_loses_only_output_parses(fixtures: Path) -> None:
    output = _output().replace('"unresolved"', '"open"')
    assert _earned(output, KEY, fixtures) == {
        "output_parses": 0,
        "none_missed": 35,
        "none_wrongly_named": 35,
        "evidence": 20,
    }
    assert grade(output, KEY, fixtures).score == 90


def test_a_finding_that_contradicts_the_list_loses_output_parses(fixtures: Path) -> None:
    output = _output(finding="none_found")
    criteria = {c.name: c for c in grade(output, KEY, fixtures).breakdown}
    assert criteria["output_parses"].earned == 0
    assert "does not match the households listed" in criteria["output_parses"].detail


def test_an_entry_with_no_household_id_is_a_problem(fixtures: Path) -> None:
    output = _output(households=[_entry("HH-0001", *EVIDENCE), {"agreement_id": "AGR-0002-1"}])
    criteria = {c.name: c for c in grade(output, KEY, fixtures).breakdown}
    assert criteria["output_parses"].detail == "households[1] names no household_id"
    assert grade(output, KEY, fixtures).passed


@pytest.mark.parametrize("key", [KEY, CLEAN_BOOK], ids=["a household found", "a clean book"])
@pytest.mark.parametrize(
    "output",
    ["No household is.", _output(finding="none")],
    ids=["no json block", "no valid finding"],
)
def test_an_answer_that_names_no_readable_set_scores_nothing(fixtures: Path, key: ListKey, output: str) -> None:
    # On a clean book an unreadable answer would otherwise miss nothing and wrongly name nothing.
    result = grade(output, key, fixtures)
    assert (result.score, result.passed) == (0, False)
    assert result.counts == NO_COUNTS


def test_the_grade_writes_as_json(fixtures: Path) -> None:
    data = grade(_output(), KEY, fixtures).to_dict()
    assert [c["name"] for c in data["breakdown"]] == ["output_parses", "none_missed", "none_wrongly_named", "evidence"]
    assert [c["points"] for c in data["breakdown"]] == [10, 35, 35, 20]
    assert data["counts"] == NO_COUNTS
    json.dumps(data)
