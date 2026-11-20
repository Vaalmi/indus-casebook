"""`casebook run` end to end on the stand-in: key, run on real tickers, grade, map back to aliases."""

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from casebook.cli import main
from casebook.keys.fee_reconciliation import fee_key
from casebook.notice import NOTICE
from casebook.publish.gates import synthetic_problems
from casebook.publish.mapper import MappingError, map_to_aliases
from casebook.runner.run import GradeRefusedError
from casebook.securities.scan import default_scan

from .conftest import ROOT, StandIn

TASKS = ROOT / "tasks" / "public"


def answer_for(real_book: Path, extra: str = "") -> str:
    key = fee_key(real_book / "households" / "HH-4821", date(2026, 3, 31))
    block = {
        "finding": key.finding,
        "debited_fee": str(key.debited_fee),
        "correct_fee": str(key.correct_fee),
        "amount_misbilled": str(key.amount_misbilled),
        "figures": [
            {"label": "fees debited", "value": str(key.debited_fee), "source": "crm/crm.json", "computed": True}
        ],
        "explanation": "The householding agreement joins the three accounts.",
    }
    return f"{extra}\n```json\n{json.dumps(block)}\n```\n"


def run(tmp_path: Path, real_book: Path, arm: str) -> int:
    paths = ["--keys", str(tmp_path / "keys"), "--runs", str(tmp_path / "runs")]
    return main(["run", "--task", "T-REC-01", "--arm", arm, "--book", str(real_book), "--tasks", str(TASKS), *paths])


def test_a_run_is_keyed_graded_and_published_under_aliases(
    tmp_path: Path, real_book: Path, standin_cli: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    standin_cli.answer.write_text(
        answer_for(real_book, "Ngozi's VTI and JNJ holdings (Johnson & Johnson) were billed alone.")
    )
    assert run(tmp_path, real_book, "skill") == 0
    assert "mapped, score 100" in capsys.readouterr().out
    [record_file] = (tmp_path / "runs" / "T-REC-01").glob("*[0-9a-f].json")
    record = json.loads(record_file.read_text())
    assert record["state"] == "mapped" and record["grade"]["passed"] is True
    assert (
        "Larkspur Total Market Fund and Halvern Health Holdings holdings (Halvern Health Holdings)" in record["output"]
    )
    published = "".join(p.read_text() for p in (tmp_path / "runs").rglob("*") if p.is_file())
    assert default_scan().find(published) == []
    key = json.loads((tmp_path / "keys" / "0.0.1" / "T-REC-01.json").read_text())
    assert key["finding"] == "fee_error"


def test_a_published_run_that_quotes_a_price_carries_the_notice_and_passes_the_synthetic_gate(
    tmp_path: Path, real_book: Path, standin_cli: StandIn
) -> None:
    # The live pass's answers quote prices ("$216.06 a share"); the site refused ten of their files until the
    # notice, whose "SYNTHETIC" labels them, went into every published record and transcript.
    standin_cli.answer.write_text(answer_for(real_book, "VTI was priced at $216.06 a share on the statement."))
    run(tmp_path, real_book, "basic")
    [record_file] = (tmp_path / "runs" / "T-REC-01").glob("*[0-9a-f].json")
    [transcript] = (tmp_path / "runs" / "T-REC-01").glob("*.transcript.jsonl")
    assert json.loads(record_file.read_text())["notice"] == NOTICE
    assert json.loads(transcript.read_text().splitlines()[0]) == {"notice": NOTICE}
    assert "$216.06 a share" in transcript.read_text() + record_file.read_text()
    assert synthetic_problems(tmp_path / "runs") == []


def test_a_failed_run_is_published_with_its_reason_and_no_grade(
    tmp_path: Path, real_book: Path, standin_cli: StandIn
) -> None:
    standin_cli.set("quota")
    assert run(tmp_path, real_book, "basic") == 1
    [record_file] = (tmp_path / "runs" / "T-REC-01").glob("*[0-9a-f].json")
    record = json.loads(record_file.read_text())
    assert (record["state"], record["failure_reason"], record["grade"]) == ("failed", "quota", None)


def test_the_mapper_refuses_what_it_cannot_map(monkeypatch: pytest.MonkeyPatch) -> None:
    from casebook.publish import mapper

    def unchanged(text: str) -> str:
        return text

    monkeypatch.setattr(mapper, "alias_mapper", lambda: unchanged)
    with pytest.raises(MappingError, match="MSFT"):
        map_to_aliases({"output": "Sell MSFT"})


def test_the_mapper_maps_names_tickers_and_issuers() -> None:
    mapped = map_to_aliases({"a": ["Microsoft and MSFT", "the Vanguard Total Bond Market fund, BND"], "VTI": 1})
    assert mapped == {
        "a": [
            "Orrin Software Group and Orrin Software Group",
            "the Larkspur Core Bond Fund fund, Larkspur Core Bond Fund",
        ],
        "Larkspur Total Market Fund": 1,
    }


def test_the_mapper_maps_a_real_ticker_written_in_lower_case() -> None:
    """Whole-branch review, reviewer B: "Trim msft." kept its real ticker."""
    assert map_to_aliases({"output": "Trim msft and aapl."}) == {
        "output": "Trim Orrin Software Group and Bramwell Devices Group."
    }


def test_a_household_absent_from_the_manifest_is_refused_before_the_key_is_computed(
    tmp_path: Path, real_book: Path, standin_cli: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    # Reviewers A (S4) and B (S3), slice 2 round 1: the key read a missing household first.
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    text = (TASKS / "T-REC-01.toml").read_text().replace('household_id = "HH-4821"', 'household_id = "HH-0000"')
    (tasks / "T-REC-01.toml").write_text(text)
    paths = ["--keys", str(tmp_path / "keys"), "--runs", str(tmp_path / "runs")]
    code = main(
        ["run", "--task", "T-REC-01", "--arm", "basic", "--book", str(real_book), "--tasks", str(tasks), *paths]
    )
    assert code == 2
    assert "UnknownHouseholdError: household HH-0000 is not in the book manifest" in capsys.readouterr().err
    assert not (tmp_path / "keys").exists()


def test_a_key_changed_after_the_run_refuses_the_grade(
    tmp_path: Path, real_book: Path, standin_cli: StandIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reviewer B, slice 2 round 1, S7 (a note): the grade used the key held in memory.
    from casebook.runner import session

    real_run = session.run_task

    def run_then_tamper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        record = real_run(*args, **kwargs)
        (tmp_path / "keys" / "0.0.1" / "T-REC-01.json").write_text("{}\n")
        return record

    monkeypatch.setattr(session, "run_task", run_then_tamper)
    standin_cli.answer.write_text(answer_for(real_book))
    with pytest.raises(GradeRefusedError, match="the answer changed since the run"):
        run(tmp_path, real_book, "basic")


def test_release_files_are_kept_in_the_repo_so_a_tag_builds_the_task_pages() -> None:
    # Reviewers A and B, slice 2 round 1, S5: run records lived only under the ignored out/.
    from casebook.cli import PUBLISHED_KEYS, PUBLISHED_RUNS

    ignored = (ROOT / ".gitignore").read_text().split()
    assert not any(
        str(PUBLISHED_RUNS).startswith(i.rstrip("/")) or str(PUBLISHED_KEYS).startswith(i.rstrip("/")) for i in ignored
    )
    workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text()
    # Since slice 16 the release builds the site inside its bundle, from the same committed files.
    assert "uv run casebook release --preview\n" in workflow
