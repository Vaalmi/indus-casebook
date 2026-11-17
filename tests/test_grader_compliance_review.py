"""What the compliance graders share: the schema rule every compliance task meets, and the book-level lists of
T-CMP-05 and T-CMP-06 graded through `graders.household_list` with their issues for reviewer attention."""

import dataclasses
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.compliance_review import grade_household_list
from casebook.keys.ips_review import IpsSweepKey, ips_sweep_key
from casebook.keys.source_disagreements import Disagreement, SourceDisagreementsKey, source_disagreements_key
from casebook.tasks.fixtures import load_task_fixtures
from casebook.tasks.schemas import compliance_prompt_problems, compliance_schema_problems
from casebook.tasks.task import BOOK, TaskFormatError, load_task

from .conftest import ROOT

AS_OF = date(2026, 4, 15)
COMPLIANCE_TASKS = sorted((ROOT / "tasks" / "public").glob("T-CMP-*.toml"))


def test_six_compliance_tasks_each_with_a_schema_that_passes() -> None:
    assert [p.stem for p in COMPLIANCE_TASKS] == [f"T-CMP-0{i}" for i in range(1, 7)]
    for path in COMPLIANCE_TASKS:
        task = load_task(path)
        assert task.workflow == "compliance"
        assert compliance_schema_problems(task.expected_output.fields) == [], task.task_id
        # The context the owner's decision of 16 November 2026 sets, in every prompt.
        for words in (
            "an SEC-registered investment adviser acting as a fiduciary; not a broker-dealer, law firm or CPA firm",
            "the firm's chief compliance officer",
            "an internal compliance memo",
            "The firm's policy:",
        ):
            assert words in task.prompt, (task.task_id, words)


@pytest.mark.parametrize(
    "field", ["legal_conclusion", "violation", "is_compliant", "nonCompliant", "ruling", "breach_determination"]
)
def test_a_schema_with_a_legal_conclusion_field_fails(field: str) -> None:
    problems = compliance_schema_problems(["finding", field, "issues_for_reviewer", "explanation"])
    assert problems == [f"field {field!r} would hold a legal conclusion"]


def test_a_schema_without_issues_for_reviewer_fails() -> None:
    assert compliance_schema_problems(["finding", "explanation"]) == ["no 'issues_for_reviewer' field"]


def test_a_compliance_task_file_with_a_legal_conclusion_field_is_refused_when_it_loads(tmp_path: Path) -> None:
    text = COMPLIANCE_TASKS[0].read_text().replace('"issues_for_reviewer", ', '"legal_conclusion", ', 1)
    (tmp_path / "T-CMP-01.toml").write_text(text)
    with pytest.raises(TaskFormatError, match="field 'legal_conclusion' would hold a legal conclusion"):
        load_task(tmp_path / "T-CMP-01.toml")


@pytest.mark.parametrize(
    ("what", "words"),
    [
        ("firm capacity", "not a broker-dealer, law firm or CPA firm"),
        ("audience", "the firm's chief compliance officer"),
        ("channel", "an internal compliance memo"),
        ("firm policy", "The firm's policy: "),
    ],
)
def test_a_compliance_prompt_missing_its_context_is_refused(tmp_path: Path, what: str, words: str) -> None:
    text = COMPLIANCE_TASKS[0].read_text().replace(words, "something else")
    (tmp_path / "T-CMP-01.toml").write_text(text)
    with pytest.raises(TaskFormatError, match=f"does not state the {what}"):
        load_task(tmp_path / "T-CMP-01.toml")
    assert compliance_prompt_problems(load_task(COMPLIANCE_TASKS[0]).prompt) == []


SWEEP = {
    "HH-0221": (["SEC-0040"], []),
    "HH-0376": (["SEC-0032"], []),
    "HH-0816": (["SEC-0005"], []),
    "HH-0984": (["SEC-0048"], []),
    "HH-3058": (["SEC-0028"], ["US equity", "International equity", "Fixed income"]),
    "HH-3462": ([], ["Fixed income"]),
    **{
        h: ([], ["US equity", "Fixed income"])
        for h in ("HH-5271", "HH-5814", "HH-6047", "HH-6590", "HH-9234", "HH-9571")
    },
}


@pytest.fixture(scope="module")
def ips(full_book: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[IpsSweepKey, Path]:
    fixtures = tmp_path_factory.mktemp("ips")
    load_task_fixtures(full_book, BOOK, ("custodian", "portfolio", "crm"), AS_OF, fixtures)
    return ips_sweep_key(full_book, AS_OF), fixtures


def _ips_answer(sweep: dict[str, tuple[list[str], list[str]]] = SWEEP, **fields: Any) -> str:
    answer: dict[str, Any] = {
        "finding": "found",
        "households": [
            {
                "household_id": h,
                "above_concentration_limit": s,
                "outside_band": c,
                "explanation": "No exception on file.",
            }
            for h, (s, c) in sweep.items()
        ],
        "unresolved": [],
        "issues_for_reviewer": [
            {
                "issue": "No IPS exception anywhere in the CRM",
                "records": sorted(sweep),
                "what_the_records_show": "No household's CRM records an exception.",
                "why_the_reviewer_should_look": "Each crossing needs a client-signed exception or a rebalance.",
            }
        ],
        "figures": [
            {
                "label": "HH-3058 Bramwell Devices Group, joint",
                "value": "825134.04",
                "source": "households/HH-3058/custodian/positions.csv",
            }
        ],
        "explanation": "Five executives hold their employer stock above the limit; eight households drift.",
    }
    answer.update(fields)
    return f"```json\n{json.dumps(answer, indent=2)}\n```\n"


def test_a_clean_sweep_answer_passes(ips: tuple[IpsSweepKey, Path]) -> None:
    result = grade_household_list(_ips_answer(), *ips)
    assert (result.score, result.passed, result.critical_fail) == (100, True, None)
    assert result.counts == {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 0}


def test_a_sweep_answer_without_issues_for_reviewer_does_not_parse(ips: tuple[IpsSweepKey, Path]) -> None:
    answer = json.loads(_ips_answer().split("```json\n")[1].split("```")[0])
    del answer["issues_for_reviewer"]
    result = grade_household_list(f"```json\n{json.dumps(answer)}\n```", *ips)
    parses = next(c for c in result.breakdown if c.name == "output_parses")
    assert parses.earned == 0 and "issues_for_reviewer" in parses.detail
    assert result.score == 90


def test_a_fund_called_a_concentration_is_a_false_alarm(ips: tuple[IpsSweepKey, Path]) -> None:
    result = grade_household_list(_ips_answer({**SWEEP, "HH-4821": (["SEC-0001", "SEC-0003"], [])}), *ips)
    assert not result.passed
    assert result.counts["false_alarm"] == 1


def test_a_drift_missed_fails(ips: tuple[IpsSweepKey, Path]) -> None:
    result = grade_household_list(_ips_answer({h: v for h, v in SWEEP.items() if h != "HH-3462"}), *ips)
    assert not result.passed


def test_a_class_left_unnamed_loses_the_evidence(ips: tuple[IpsSweepKey, Path]) -> None:
    result = grade_household_list(
        _ips_answer({**SWEEP, "HH-3058": (["SEC-0028"], ["US equity", "Fixed income"])}), *ips
    )
    assert {c.name: c.earned for c in result.breakdown}["evidence"] == 0
    assert result.score == 80


def test_a_sweep_key_clearing_one_household_fails_the_clean_answer(ips: tuple[IpsSweepKey, Path]) -> None:
    key, fixtures = ips
    review = key.reviews["HH-3462"]
    cleared = dataclasses.replace(key, reviews={**key.reviews, "HH-3462": dataclasses.replace(review, drifts=())})
    assert not grade_household_list(_ips_answer(), cleared, fixtures).passed


@pytest.fixture(scope="module")
def sources(full_book: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[SourceDisagreementsKey, Path]:
    fixtures = tmp_path_factory.mktemp("sources")
    load_task_fixtures(full_book, BOOK, ("custodian", "portfolio", "crm"), AS_OF, fixtures)
    return source_disagreements_key(full_book), fixtures


def _sources_answer(**fields: Any) -> str:
    answer: dict[str, Any] = {
        "finding": "none_found",
        "households": [],
        "unresolved": [],
        "issues_for_reviewer": [
            {
                "issue": "Beneficiary designation names a deceased spouse",
                "records": ["SYN-01930002", "CA-0193-03"],
                "what_the_records_show": "Every source agrees the designation still names Omar Wainwright.",
                "why_the_reviewer_should_look": "The change form sent has not come back.",
            }
        ],
        "figures": [],
        "explanation": "Every source states each owner, person and beneficiary alike.",
    }
    answer.update(fields)
    return f"```json\n{json.dumps(answer, indent=2)}\n```\n"


def test_a_correct_none_found_passes(sources: tuple[SourceDisagreementsKey, Path]) -> None:
    result = grade_household_list(_sources_answer(), *sources)
    assert (result.score, result.passed) == (100, True)
    assert result.counts == {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 0}


def test_an_out_of_date_record_named_as_a_disagreement_is_a_false_alarm(
    sources: tuple[SourceDisagreementsKey, Path],
) -> None:
    entry = {"household_id": "HH-0193", "records": ["SYN-01930002"], "explanation": "Names a deceased beneficiary."}
    result = grade_household_list(_sources_answer(finding="found", households=[entry]), *sources)
    assert not result.passed
    assert result.counts["false_alarm"] == 1


def test_a_blanket_refusal_is_an_unnecessary_refusal(sources: tuple[SourceDisagreementsKey, Path]) -> None:
    result = grade_household_list(_sources_answer(finding="unresolved"), *sources)
    assert not result.passed
    assert result.counts["unnecessary_refusal"] == 1


def test_a_key_finding_one_disagreement_fails_the_clean_answer(sources: tuple[SourceDisagreementsKey, Path]) -> None:
    key, fixtures = sources
    found = {**key.disagreements, "HH-0193": (Disagreement("SYN-01930002", "a changed designation"),)}
    assert not grade_household_list(_sources_answer(), dataclasses.replace(key, disagreements=found), fixtures).passed
