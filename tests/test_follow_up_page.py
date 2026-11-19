"""A task page shows each juror's tone vote and what the run wrote to the CRM sandbox (docs/PLAN.md, slice
10: "each vote is stored"; "the run record holds the sandbox diff"). A held task's page shows the CRM writes,
which are output, but no vote, which is verdict."""

from pathlib import Path
from typing import Any

from casebook.publish.site_build import build_site
from casebook.runner.session import published_record
from casebook.tasks.task import find_task

from .conftest import README, ROOT
from .test_held_verdicts import a_graded_record, runs_with

TASKS = ROOT / "tasks" / "public"

DIFF = {
    "households": {
        "HH-4821": {
            "added": [
                {
                    "collection": "notes",
                    "record_id": "SB-4821-01",
                    "after": {"note_id": "SB-4821-01", "date": "2026-04-15", "text": "Discussed the fee refund."},
                },
                {
                    "collection": "activities",
                    "record_id": "SB-4821-02",
                    "after": {
                        "activity_id": "SB-4821-02",
                        "date": "2026-04-15",
                        "kind": "message",
                        "summary": "Wrote to the client about the refund.",
                        "sent_to_client": True,
                    },
                },
            ],
            "changed": [],
            "removed": [],
        }
    }
}


def vote(family: str, name: str, score: int | None) -> dict[str, Any]:
    voted = score is not None
    return {
        "family": family,
        "name": name,
        "model": "m",
        "effort": "high",
        "command": ["cli"],
        "score": score,
        "reason": f"{name} found it plain." if voted else None,
        "error": None if voted else "timed out after 600 s",
        "raw": "",
        "log": "",
    }


JURORS = (("claude_high", "Claude"), ("sol", "Sol"), ("carbon", "Carbon"))


def with_follow_up(task_id: str, scores: tuple[int | None, ...]) -> dict[str, Any]:
    record = a_graded_record(task_id)
    votes = [vote(family, name, score) for (family, name), score in zip(JURORS, scores, strict=True)]
    given = sorted(s for s in scores if s is not None)
    complete = len(given) == len(scores)
    tone = {"score": given[1] if complete else None, "complete": complete, "votes": votes}
    return record | {"crm_sandbox_diff": DIFF, "grade": record["grade"] | {"tone": tone}}


def page(book: Path, tmp_path: Path, record: dict[str, Any]) -> str:
    build_site(book, tmp_path / "site", README, runs_with(tmp_path, record), TASKS, None)
    return (tmp_path / "site" / "tasks" / f"{record['task_id']}.html").read_text()


def test_a_task_page_shows_every_vote_and_the_crm_writes(book: Path, tmp_path: Path) -> None:
    html = page(book, tmp_path, with_follow_up("T-REC-05", (4, 5, 3)))
    assert "median 4 of 5" in html
    for juror in ("claude_high", "sol", "carbon"):
        assert f'data-juror="{juror}"' in html
    assert "Sol found it plain." in html
    assert 'data-section="crm-diff"' in html and "Discussed the fee refund." in html
    assert "Wrote to the client about the refund. (sent to the client)" in html


def test_a_missing_vote_is_shown_as_missing(book: Path, tmp_path: Path) -> None:
    html = page(book, tmp_path, with_follow_up("T-REC-05", (4, None, 3)))
    assert "a vote is missing, so no tone score and no pass" in html
    assert "No vote: timed out after 600 s" in html


def test_a_held_task_page_shows_the_crm_writes_but_no_vote(book: Path, tmp_path: Path) -> None:
    """Published as a held run is: its grade, votes and all, stripped (a held record with its grade fails the
    site build's gate)."""
    record = published_record(find_task(TASKS, "T-TAX-01"), with_follow_up("T-TAX-01", (4, 5, 3)))
    html = page(book, tmp_path, record)
    assert "Discussed the fee refund." in html
    assert "data-juror" not in html and "median 4 of 5" not in html


def test_a_run_with_no_crm_writes_says_so(book: Path, tmp_path: Path) -> None:
    record = a_graded_record("T-REC-05") | {"crm_sandbox_diff": {"households": {}}}
    assert "Nothing: the run wrote no CRM record." in page(book, tmp_path, record)


def test_a_task_with_no_sandbox_shows_no_crm_section(book: Path, tmp_path: Path) -> None:
    assert 'data-section="crm-diff"' not in page(book, tmp_path, a_graded_record("T-REC-05"))
