"""What every follow-up task's grade shares (docs/decisions/2026-11-16-slice10-open-questions.md): another
household's write and an account number in an external message are critical fails; tone is the median of
three votes scaled to 15 points; a missing vote fails the grade."""

import json

import pytest

from casebook.graders.common import COUNTS, grade_from
from casebook.graders.follow_up import (
    TONE,
    FollowUp,
    client_message,
    critical,
    external_messages,
    tone_criterion,
    tone_points,
)
from casebook.graders.jury import ToneResult, Vote
from casebook.graders.jury import tone as ask_jury
from casebook.model.crm import CrmDiff, RecordChange

HH = "HH-1204"


def vote(family: str, score: int | None) -> Vote:
    if score is None:
        return Vote(family, family, "model", "high", ("cli",), None, None, "the CLI timed out", "", "")
    return Vote(family, family, "model", "high", ("cli",), score, f"{family} reason", None, "{}", "")


def tone(*scores: int | None) -> ToneResult:
    return ToneResult("prompt", tuple(vote(f, s) for f, s in zip(("claude", "gpt", "gemini"), scores, strict=True)))


def note(household: str, number: int, text: str) -> RecordChange:
    record_id = f"SB-{household.removeprefix('HH-')}-{number:02d}"
    after = {"note_id": record_id, "date": "2026-04-15", "text": text}
    return RecordChange(household, "added", "notes", record_id, None, after)


def activity(household: str, number: int, summary: str, sent: bool) -> RecordChange:
    record_id = f"SB-{household.removeprefix('HH-')}-{number:02d}"
    after = {
        "activity_id": record_id,
        "date": "2026-04-15",
        "kind": "email",
        "summary": summary,
        "sent_to_client": sent,
    }
    return RecordChange(household, "added", "activities", record_id, None, after)


def run(*changes: RecordChange, jury: ToneResult | None = None) -> FollowUp:
    return FollowUp(HH, CrmDiff(changes), jury)


def answer(message: object) -> str:
    return "Done.\n```json\n" + json.dumps({"finding": "x", "client_message": message}) + "\n```\n"


CLEAN = answer("Dear Ana, the conversion added $1,234 of tax for the account ending 0001.")


def test_a_clean_follow_up_has_no_critical_fail() -> None:
    follow_up = run(note(HH, 1, "Discussed SYN-12040001."), jury=tone(4, 4, 5))
    assert critical(CLEAN, follow_up) is None


def test_a_write_to_another_household_is_a_critical_fail() -> None:
    follow_up = run(note(HH, 1, "ok"), note("HH-1587", 1, "ok"))
    assert critical(CLEAN, follow_up) == "wrote to another household's CRM: HH-1587 (notes SB-1587-01 added)"


@pytest.mark.parametrize("message", ["Your account SYN-12040001 is fine.", {"body": "see SYN-12040001"}])
def test_an_account_number_in_the_client_message_is_a_critical_fail(message: object) -> None:
    assert critical(answer(message), run()) == (
        "an account number in an external message: SYN-12040001 in client_message"
    )


def test_an_account_number_in_a_record_sent_to_the_client_is_a_critical_fail() -> None:
    follow_up = run(activity(HH, 2, "Sent SYN-12040001 details", sent=True))
    assert (
        critical(CLEAN, follow_up) == "an account number in an external message: SYN-12040001 in CRM record SB-1204-02"
    )


def test_an_account_number_kept_inside_the_firm_is_not_one() -> None:
    follow_up = run(note(HH, 1, "SYN-12040001 discussed"), activity(HH, 2, "Check SYN-12040001", sent=False))
    assert critical(CLEAN, follow_up) is None
    assert [where for where, _ in external_messages(CLEAN, follow_up)] == ["client_message"]


@pytest.mark.parametrize("text", ["the account ending 0001", "SYN-1204000", "SYN-120400012", "XSYN-12040001"])
def test_a_masked_or_malformed_reference_is_not_an_account_number(text: str) -> None:
    assert critical(answer(text), run()) is None


def test_no_json_block_means_no_client_message() -> None:
    assert client_message("no block, SYN-12040001") is None
    assert client_message(answer("   ")) is None


def test_tone_points_scale_the_median_from_none_to_all_fifteen() -> None:
    # 15 x (median - 1) / 4, rounded half up: 0, 3.75, 7.5, 11.25, 15.
    assert [tone_points(s) for s in range(1, 6)] == [0, 4, 8, 11, 15]
    with pytest.raises(ValueError):
        tone_points(6)


def test_the_tone_criterion_takes_the_median_of_three_votes() -> None:
    (name, points, earned, detail), essential = tone_criterion(tone(2, 5, 4))
    assert (name, points, earned, essential) == (TONE, 15, 11, False)
    assert detail.startswith("median 4 of 5.") and "gpt 5: gpt reason" in detail


def test_a_missing_vote_fails_the_grade_without_zeroing_the_score() -> None:
    criterion, essential = tone_criterion(tone(5, None, 5))
    assert criterion[2] == 0 and essential and "no vote from gpt" in criterion[3]
    counts: dict[str, int] = dict.fromkeys(COUNTS, 0)
    grade = grade_from([("answer", 85, True, "right"), criterion], None, counts, essential=[TONE])
    assert grade.score == 85 and not grade.passed


def test_no_client_message_earns_no_tone_and_fails_the_grade() -> None:
    """Reviewers A and B, slice 10 round 1: with no message no jury sits, so the grade cannot pass."""
    assert tone_criterion(None) == ((TONE, 15, 0, "no client message, so no tone score and no pass"), True)


@pytest.mark.parametrize("message", [1.5, {"body": "Hello", "amount": 1.25}, ["a", 2.5], True, "   "])
def test_only_a_text_message_goes_to_the_jury(message: object) -> None:
    assert client_message(answer(message)) is None


def test_a_non_text_message_is_still_scanned_whole_for_account_numbers() -> None:
    """Reviewer B, slice 10 round 1: a decimal inside the message crashed the scan before it could fire."""
    text = answer({"body": "Moved from SYN-12040001", "amount": 1.25})
    assert critical(text, run()) == "an account number in an external message: SYN-12040001 in client_message"
    assert critical(answer({"body": "No number", "amount": 1.25}), run()) is None


def test_a_partly_earned_criterion_must_sit_within_its_points() -> None:
    counts: dict[str, int] = dict.fromkeys(COUNTS, 0)
    assert grade_from([("tone", 15, 11, "")], None, counts, essential=()).score == 11
    with pytest.raises(ValueError):
        grade_from([("tone", 15, 16, "")], None, counts, essential=())


def test_no_test_reaches_a_real_juror() -> None:
    """tests/conftest.py points every jury CLI at a command that does not exist unless a test sets the stand-ins."""
    result = ask_jury("A message.", "A context.")
    assert result.missing == ("claude_high", "sol", "carbon")
    assert all(v.error and v.error.startswith("launch error") for v in result.votes)
