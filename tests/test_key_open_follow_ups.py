"""The open follow-ups key (T-MTG-05): each kind of follow-up on hand-built CRMs, the whole book at the cutoff
and earlier, and the household-list grader on its key."""

import dataclasses
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.household_list import grade
from casebook.keys.open_follow_ups import UnsettledFollowUpError, household_follow_ups, open_follow_ups_key
from casebook.model.files import (
    ACCOUNTS_COLUMNS,
    ACCOUNTS_CSV,
    CRM_JSON,
    TRANSACTIONS_COLUMNS,
    TRANSACTIONS_CSV,
    csv_text,
    json_text,
)
from casebook.tasks.fixtures import load_task_fixtures
from casebook.tasks.task import BOOK

AS_OF = date(2026, 4, 15)
JOINT, IRA, ROTH = "SYN-00010001", "SYN-00010002", "SYN-00010003"


def _row(columns: tuple[str, ...], **values: str) -> dict[str, str]:
    return {**dict.fromkeys(columns, ""), **values}


def _account(account_id: str, kind: str) -> dict[str, str]:
    return _row(ACCOUNTS_COLUMNS, account_id=account_id, account_type=kind)


def _transaction(transaction_id: str, account_id: str, day: str, kind: str, amount: str) -> dict[str, str]:
    return _row(
        TRANSACTIONS_COLUMNS,
        transaction_id=transaction_id,
        account_id=account_id,
        trade_date=day,
        settle_date=day,
        type=kind,
        amount=amount,
        known_as_of=day,
    )


def _activity(activity_id: str, day: str, kind: str, summary: str) -> dict[str, Any]:
    return {"activity_id": activity_id, "date": day, "kind": kind, "summary": summary, "known_as_of": day}


def household(
    root: Path, activities: list[dict[str, Any]], transactions: list[dict[str, str]], notes: Any = ()
) -> Path:
    """A joint account, a traditional IRA and a Roth IRA, with the CRM activities and transactions given."""
    accounts = [_account(JOINT, "joint_taxable"), _account(IRA, "traditional_ira"), _account(ROTH, "roth_ira")]
    files = {
        ACCOUNTS_CSV: csv_text(ACCOUNTS_COLUMNS, accounts),
        TRANSACTIONS_CSV: csv_text(TRANSACTIONS_COLUMNS, transactions),
        CRM_JSON: json_text({"household_id": "HH-0001", "activities": activities, "notes": list(notes)}),
    }
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root


def open_ids(root: Path, as_of: date = AS_OF) -> list[str]:
    _, follow_ups = household_follow_ups(root, as_of)
    return [f.activity_id for f in follow_ups if f.open]


QCD = _activity(
    "CA-1", "2025-03-31", "qcd_request", f"QCD request: pay $5,000.00 from IRA {IRA} directly to a public charity."
)
CONVERT = _activity(
    "CA-2",
    "2025-06-01",
    "meeting",
    f"Conversion planning: convert $20,000.00 from the traditional IRA {IRA} to the Roth IRA {ROTH} this year.",
)
STEP_UP = _activity(
    "CA-3",
    "2025-08-06",
    "custodian_request",
    f"Sent the custodian the death certificate and asked for each lot in joint account {JOINT} to be stepped up.",
)
FORM_SENT = _activity(
    "CA-4", "2025-09-01", "beneficiary_form_sent", f"Sent a beneficiary change form for {IRA}. Not yet returned."
)
SALE = _activity(
    "CA-5", "2025-11-20", "call", "Called for cash from the joint account. Agreed to sell part of the fund."
)


def test_a_qcd_paid_in_the_amount_requested_has_happened(tmp_path: Path) -> None:
    assert open_ids(household(tmp_path, [QCD], [_transaction("T-1", IRA, "2025-04-08", "QCD", "-5000.00")])) == []


def test_a_qcd_paid_in_another_amount_is_still_open(tmp_path: Path) -> None:
    assert open_ids(household(tmp_path, [QCD], [_transaction("T-1", IRA, "2025-04-08", "QCD", "-4000.00")])) == ["CA-1"]


def test_an_agreed_conversion_happens_when_the_roth_ira_receives_it(tmp_path: Path) -> None:
    done = [_transaction("T-1", ROTH, "2025-09-10", "CONVERSION_IN", "20000.00")]
    assert open_ids(household(tmp_path / "done", [CONVERT], done)) == []
    # A conversion before the meeting is not the one it agreed.
    early = [_transaction("T-1", ROTH, "2025-05-10", "CONVERSION_IN", "20000.00")]
    assert open_ids(household(tmp_path / "early", [CONVERT], early)) == ["CA-2"]


def test_a_sale_agreed_on_a_call_happens_in_the_joint_account(tmp_path: Path) -> None:
    assert open_ids(household(tmp_path, [SALE], [_transaction("T-1", JOINT, "2025-12-08", "SELL", "100.00")])) == []


def test_a_step_up_counts_whenever_the_custodian_dates_it(tmp_path: Path) -> None:
    # The custodian books a step-up as of the death, before the request that asked for it.
    booked = [_transaction("T-1", JOINT, "2025-07-29", "STEP_UP", "0")]
    assert open_ids(household(tmp_path / "booked", [STEP_UP], booked)) == []
    assert open_ids(household(tmp_path / "not", [STEP_UP], [])) == ["CA-3"]


def test_a_beneficiary_form_is_open_until_a_later_activity_receives_it(tmp_path: Path) -> None:
    received = _activity("CA-9", "2025-10-01", "beneficiary_form_received", f"Received the signed change for {IRA}.")
    assert open_ids(household(tmp_path / "back", [FORM_SENT, received], [])) == []
    assert open_ids(household(tmp_path / "out", [FORM_SENT], [])) == ["CA-4"]
    # Received after the cutoff: not known on the day asked about.
    assert open_ids(household(tmp_path / "back", [FORM_SENT, received], []), date(2025, 9, 15)) == ["CA-4"]


def test_records_of_what_happened_are_not_follow_ups(tmp_path: Path) -> None:
    done = _activity("CA-1", "2026-02-12", "document_received", "2025 Forms W-2 received.")
    review = {
        "note_id": "N-1",
        "date": "2025-10-14",
        "known_as_of": "2025-10-14",
        "template": "annual_review",
        "text": "Annual review. No changes requested.",
    }
    assert household_follow_ups(household(tmp_path, [done], [], [review]), AS_OF)[1] == ()


@pytest.mark.parametrize(
    ("activities", "notes"),
    [
        ([_activity("CA-1", "2025-05-01", "phone_message", "Call the client back.")], []),
        ([_activity("CA-1", "2025-05-01", "meeting", "Talked about the markets.")], []),
        ([], [{"note_id": "N-1", "known_as_of": "2025-05-01", "template": None, "text": "Will rebalance in June."}]),
    ],
    ids=["an unknown activity kind", "a meeting with no step the key can read", "a note not from a template"],
)
def test_a_record_the_key_cannot_read_is_refused(tmp_path: Path, activities: Any, notes: Any) -> None:
    with pytest.raises(UnsettledFollowUpError):
        household_follow_ups(household(tmp_path, activities, [], notes), AS_OF)


def test_the_whole_book_finds_five_households_with_an_open_follow_up(full_book: Path) -> None:
    key = open_follow_ups_key(full_book, AS_OF)
    # Archetype 8's five traps, the featured HH-8312 (public since the freeze) and the four in the background: the
    # custodian has booked no step-up for the deceased spouse's half of the joint account, and four of the five
    # survivors have not returned the beneficiary form. HH-8312 asked for the step-up on SYN-83120001 on
    # 2025-06-24 (CA-8312-02) and sent the form for SYN-83120002 on 2025-07-08 (CA-8312-03); its custodian files
    # hold no STEP_UP and its CRM no later form received. Archetype 7's pair each signed a beneficiary claim
    # (CA-7126-02, CA-7683-02) that the inherited IRAs SYN-71260002 and SYN-76830002 settle.
    assert dict(key.found) == {
        "HH-0168": ("CA-0168-02",),
        "HH-0193": ("CA-0193-02", "CA-0193-03"),
        "HH-0265": ("CA-0265-02", "CA-0265-03"),
        "HH-0611": ("CA-0611-02", "CA-0611-03"),
        "HH-8312": ("CA-8312-02", "CA-8312-03"),
    }
    # Their twins show the step-up booked (T-0642-0017 on the day of Olumide's death, 2025-08-01; T-8865-0011 on
    # the day of Vikram's, 2025-05-28), and HH-8865 received Helen's form on 2025-08-12 (CA-8865-03).
    (step_up,) = [f for f in key.follow_ups["HH-0642"] if f.kind == "custodian_request"]
    assert step_up.evidence == ("T-0642-0017",)
    (step_up,) = [f for f in key.follow_ups["HH-8865"] if f.kind == "custodian_request"]
    assert step_up.evidence == ("T-8865-0011",)
    assert key.unresolved == ()


def test_earlier_in_the_year_two_distribution_instructions_were_still_unpaid(full_book: Path) -> None:
    # On 20 February 2026: HH-0120 signed on 2026-02-09 for 45,492.56 from SYN-01200002, paid 2026-03-03; HH-0637
    # signed on 2026-01-28 for 32,623.00 from SYN-06370002, paid 2026-03-18. HH-0371's 2025-10-24 instruction was
    # paid on 2026-02-18, and HH-0989's on 2026-01-21, so theirs had happened. With archetype 8's five traps,
    # open since mid-2025, that is seven.
    key = open_follow_ups_key(full_book, date(2026, 2, 20))
    assert key.found["HH-0120"] == ("CA-0120-02",)
    assert key.found["HH-0637"] == ("CA-0637-03",)
    assert "HH-0371" not in key.found and "HH-0989" not in key.found
    assert len(key.found) == 7


def _answer(households: list[dict[str, Any]], finding: str = "found") -> str:
    answer = {
        "finding": finding,
        "households": households,
        "unresolved": [],
        "figures": [],
        "explanation": "The custodian booked no step-up after the requests, and four beneficiary forms are out.",
    }
    return f"```json\n{json.dumps(answer)}\n```\n"


CLEAN = [
    {"household_id": "HH-0168", "activity_ids": ["CA-0168-02"], "explanation": "No step-up booked."},
    {"household_id": "HH-0193", "activity_ids": ["CA-0193-02", "CA-0193-03"], "explanation": "Step-up and form."},
    {"household_id": "HH-0265", "activity_ids": ["CA-0265-02", "CA-0265-03"], "explanation": "Step-up and form."},
    {"household_id": "HH-0611", "activity_ids": ["CA-0611-02", "CA-0611-03"], "explanation": "Step-up and form."},
    {"household_id": "HH-8312", "activity_ids": ["CA-8312-02", "CA-8312-03"], "explanation": "Step-up and form."},
]


@pytest.fixture(scope="module")
def workspace(full_book: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("book-follow-ups")
    load_task_fixtures(full_book, BOOK, ("custodian", "crm"), AS_OF, root)
    return root


def test_the_grader_passes_the_clean_list_and_fails_a_miss_or_a_false_alarm(full_book: Path, workspace: Path) -> None:
    key = open_follow_ups_key(full_book, AS_OF)
    clean = grade(_answer(CLEAN), key, workspace)
    assert (clean.score, clean.passed) == (100, True)
    missed = grade(_answer(CLEAN[1:]), key, workspace)
    assert not missed.passed
    twin = {"household_id": "HH-0642", "activity_ids": ["CA-0642-02"], "explanation": "No step-up."}
    alarm = grade(_answer([*CLEAN, twin]), key, workspace)
    assert not alarm.passed and alarm.counts["false_alarm"] == 1
    # Naming the household without the open beneficiary form loses the evidence points.
    partial = [{**CLEAN[0]}, {**CLEAN[1], "activity_ids": ["CA-0193-02"]}, *CLEAN[2:]]
    assert {c.name: c.earned for c in grade(_answer(partial), key, workspace).breakdown}["evidence"] == 0


def test_an_altered_key_fails_the_clean_list(full_book: Path, workspace: Path) -> None:
    key = open_follow_ups_key(full_book, AS_OF)
    closed = {
        h: tuple(dataclasses.replace(f, evidence=("T-0168-0001",)) for f in fs)
        for h, fs in key.follow_ups.items()
        if h == "HH-0168"
    }
    altered = dataclasses.replace(key, follow_ups={**key.follow_ups, **closed})
    assert grade(_answer(CLEAN), key, workspace).passed
    assert not grade(_answer(CLEAN), altered, workspace).passed
