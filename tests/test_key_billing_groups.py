"""The billing groups key (T-REC-05) against a hand-built book and the built one, and key mutations the
household list grader catches."""

import dataclasses
import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.household_list import grade
from casebook.keys.billing_groups import BillingGroupsKey, Contradiction, billing_groups_key
from casebook.keys.figures import KeyFigure
from casebook.model.files import (
    CASH_COLUMNS,
    CASH_CSV,
    CRM_JSON,
    MANIFEST,
    PORTFOLIO_BILLING,
    PORTFOLIO_HOUSEHOLD,
    POSITIONS_COLUMNS,
    POSITIONS_CSV,
    TRANSACTIONS_COLUMNS,
    TRANSACTIONS_CSV,
    csv_text,
    household_dir,
    json_text,
)
from casebook.tasks.fixtures import load_task_fixtures
from casebook.tasks.task import BOOK

AS_OF = date(2026, 4, 15)
QUARTER_END = "2026-03-31"
SCHEDULE = {
    "schedule_id": "FS-STD",
    "tiers": [
        {"up_to": "1000000", "annual_rate": "0.0100"},
        {"up_to": "2000000", "annual_rate": "0.0080"},
        {"up_to": None, "annual_rate": "0.0060"},
    ],
}


def _account(household: str, n: int) -> str:
    return f"SYN-{household[3:]}000{n}"


def _householding(household: str, signed: str) -> dict[str, Any]:
    return {
        "agreement_id": f"AGR-{household[3:]}-2",
        "kind": "householding",
        "party_ids": [f"P-{household[3:]}-1"],
        "account_ids": [_account(household, 1), _account(household, 2)],
        "signed": signed,
        "known_as_of": signed,
        "summary": "Householding letter: both accounts bill as one group.",
    }


def _rows(columns: tuple[str, ...], **values: str) -> dict[str, str]:
    row = dict.fromkeys(columns, "")
    row.update(values)
    return row


def _write_household(book: Path, household: str, *, together: bool, agreements: list[dict[str, Any]]) -> None:
    """Two accounts worth 600,000.00 and 500,000.00 on 31 March 2026, each debited 1% a year for the quarter
    on 2 April 2026 (1,500.00 and 1,250.00), as if billed apart."""
    a, b = _account(household, 1), _account(household, 2)
    groups = (
        [{"billing_group_id": f"BG-{household[3:]}-1", "schedule_id": "FS-STD", "account_ids": [a, b]}]
        if together
        else [
            {"billing_group_id": f"BG-{household[3:]}-1", "schedule_id": "FS-STD", "account_ids": [a]},
            {"billing_group_id": f"BG-{household[3:]}-2", "schedule_id": "FS-STD", "account_ids": [b]},
        ]
    )
    day = "2026-04-02"
    files = {
        PORTFOLIO_HOUSEHOLD: json_text({"household_id": household, "billing_groups": groups}),
        PORTFOLIO_BILLING: json_text({"fee_schedules": [SCHEDULE]}),
        CRM_JSON: json_text({"agreements": agreements}),
        POSITIONS_CSV: csv_text(
            POSITIONS_COLUMNS,
            [
                _rows(
                    POSITIONS_COLUMNS,
                    account_id=account,
                    security_id="SEC-0001",
                    security="Larkspur Total Market Fund",
                    units="1000",
                    price=str(Decimal(value) / 1000),
                    price_label="synthetic",
                    market_value=value,
                    valuation_date=QUARTER_END,
                    known_as_of=QUARTER_END,
                )
                for account, value in ((a, "600000.00"), (b, "500000.00"))
            ],
        ),
        CASH_CSV: csv_text(
            CASH_COLUMNS,
            [
                _rows(
                    CASH_COLUMNS,
                    account_id=account,
                    settled_cash="0.00",
                    unsettled_cash="0.00",
                    valuation_date=QUARTER_END,
                    known_as_of=QUARTER_END,
                )
                for account in (a, b)
            ],
        ),
        TRANSACTIONS_CSV: csv_text(
            TRANSACTIONS_COLUMNS,
            [
                _rows(
                    TRANSACTIONS_COLUMNS,
                    transaction_id=f"T-{household[3:]}-{n}",
                    account_id=account,
                    trade_date=day,
                    settle_date=day,
                    type="FEE",
                    amount=amount,
                    description=f"Advisory fee, quarter to {QUARTER_END}",
                    valuation_date=day,
                    known_as_of=day,
                )
                for n, (account, amount) in enumerate(((a, "-1500.00"), (b, "-1250.00")))
            ],
        ),
    }
    root = book / household_dir(household)
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")


@pytest.fixture
def hand_book(tmp_path: Path) -> Path:
    """HH-0001 is billed apart against a householding agreement; HH-0002 is billed together under one; HH-0003
    is billed apart with no householding agreement; HH-0004's agreement is signed after the as-of date."""
    book = tmp_path / "book"
    _write_household(book, "HH-0001", together=False, agreements=[_householding("HH-0001", "2025-06-01")])
    _write_household(book, "HH-0002", together=True, agreements=[_householding("HH-0002", "2025-06-01")])
    _write_household(book, "HH-0003", together=False, agreements=[])
    _write_household(book, "HH-0004", together=False, agreements=[_householding("HH-0004", "2026-05-01")])
    manifest = {
        "version": "0.0.1",
        "seed": 1,
        "households": [{"household_id": f"HH-000{n}", "archetype": 10, "state": "ok"} for n in (1, 2, 3, 4)],
        "files": {},
    }
    (book / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    return book


def _figure(key: BillingGroupsKey, household: str, label: str) -> Decimal:
    figures = next(h.figures for h in key.household_figures if h.household_id == household)
    return next(f.value for f in figures if f.label == label)


def test_an_agreement_the_billing_groups_hold_apart_is_found_with_its_evidence(hand_book: Path) -> None:
    key = billing_groups_key(hand_book, AS_OF)
    assert key.checked == ("HH-0001", "HH-0002", "HH-0003", "HH-0004")
    assert dict(key.found) == {"HH-0001": ("AGR-0001-2", "BG-0001-1", "BG-0001-2")}
    assert key.unresolved == ()
    (contradiction,) = key.contradictions
    assert contradiction.signed == date(2025, 6, 1)
    assert contradiction.account_ids == ("SYN-00010001", "SYN-00010002")


def test_the_figures_price_each_household_billed_apart_or_under_an_agreement(hand_book: Path) -> None:
    key = billing_groups_key(hand_book, AS_OF)
    # Each is billed in two groups or holds a householding agreement, so each is priced.
    assert [h.household_id for h in key.household_figures] == ["HH-0001", "HH-0002", "HH-0003", "HH-0004"]
    # HH-0001 as one group: (1,000,000 x 1.00% + 100,000 x 0.80%) / 4 = 2,700.00 against 2,750.00 debited.
    # Only the quarter to 31 March 2026 has fee rows, so the totals are that quarter's.
    assert _figure(key, "HH-0001", "correct fees, every quarter") == Decimal("2700.00")
    assert _figure(key, "HH-0001", "fees debited, every quarter") == Decimal("2750.00")
    assert _figure(key, "HH-0001", "amount misbilled, quarters misbilled") == Decimal("50.00")
    # HH-0003 billed apart with no agreement: 1,500.00 + 1,250.00, exactly what was debited.
    assert _figure(key, "HH-0003", "amount misbilled, every quarter") == Decimal("0.00")


def test_the_key_writes_as_json_with_money_as_strings(hand_book: Path) -> None:
    data = billing_groups_key(hand_book, AS_OF).to_dict()
    assert data["found"] == {"HH-0001": ["AGR-0001-2", "BG-0001-1", "BG-0001-2"]}
    assert data["contradictions"][0]["signed"] == "2025-06-01"
    assert all(isinstance(f["value"], str) for f in data["computed_figures"]["HH-0001"])
    json.dumps(data)


FOUND_IN_THE_BOOK = {
    # Read from each household's crm/crm.json and portfolio/household.json: a householding agreement joining
    # accounts 1, 2 and 3, while the portfolio system bills account 3 in a group of its own.
    "HH-0586": ("AGR-0586-3", "BG-0586-1", "BG-0586-2"),
    "HH-0592": ("AGR-0592-3", "BG-0592-1", "BG-0592-2"),
    "HH-0928": ("AGR-0928-3", "BG-0928-1", "BG-0928-2"),
    "HH-4821": ("AGR-4821-3", "BG-4821-1", "BG-4821-2"),
}


def test_the_whole_book_finds_the_four_households_with_an_agreement_not_applied(full_book: Path) -> None:
    # The public book holds no private pair, so archetype 10's pair 3 (a trap and its look-alike) is not here.
    key = billing_groups_key(full_book, AS_OF)
    assert len(key.checked) == 88
    assert dict(key.found) == FOUND_IN_THE_BOOK
    # The four look-alikes are billed in the same two groups with no householding agreement: cleared, but priced.
    priced = {h.household_id for h in key.household_figures}
    assert priced == set(FOUND_IN_THE_BOOK) | {"HH-0478", "HH-0517", "HH-0572", "HH-7350"}


def test_the_trap_household_figures_hold_the_overbilling(book: Path) -> None:
    key = billing_groups_key(book, AS_OF)
    assert dict(key.found) == {"HH-4821": FOUND_IN_THE_BOOK["HH-4821"]}
    # The quarter to 31 March 2026, worked by hand in tests/test_key_fee_reconciliation.py: 4,605.18 debited
    # against 4,314.93, overbilled 290.25. Over the five quarters billed since the agreement, the registry's
    # planted figures: 22,410.73 debited against 21,000.68, overbilled 1,410.05.
    assert _figure(key, "HH-4821", "quarter to 2026-03-31: amount misbilled") == Decimal("290.25")
    assert _figure(key, "HH-4821", "fees debited, quarters misbilled") == Decimal("22410.73")
    assert _figure(key, "HH-4821", "correct fees, quarters misbilled") == Decimal("21000.68")
    assert _figure(key, "HH-4821", "amount misbilled, quarters misbilled") == Decimal("1410.05")


def test_the_key_gives_the_same_answer_on_the_real_ticker_build(book: Path, real_book: Path) -> None:
    assert billing_groups_key(real_book, AS_OF).to_dict() == billing_groups_key(book, AS_OF).to_dict()


# Key mutations: a clean answer that passes against the key fails once the key is altered.

CLEAN = {
    "finding": "found",
    "households": [
        {
            "household_id": "HH-4821",
            "agreement_id": "AGR-4821-3",
            "billing_group_ids": ["BG-4821-1", "BG-4821-2"],
            "explanation": "The agreement joins all three accounts; the portfolio system bills them in two groups.",
        }
    ],
    "unresolved": [],
    "figures": [
        {"label": "AGR-4821-3 signed", "value": "2024-11-18", "source": "households/HH-4821/crm/crm.json"},
        {
            "label": "Overbilled, quarter to 31 March 2026",
            "value": "290.25",
            "source": "households/HH-4821/custodian/transactions.csv",
            "computed": True,
        },
    ],
    "explanation": "One household's billing groups contradict its signed householding agreement.",
}


@pytest.fixture(scope="module")
def workspace(book: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("rec05")
    load_task_fixtures(book, BOOK, ("custodian", "portfolio", "crm"), AS_OF, folder)
    return folder


def _answer() -> str:
    return f"HH-4821 is billed against its agreement.\n\n```json\n{json.dumps(CLEAN, indent=2)}\n```\n"


def _without_overbilling(key: BillingGroupsKey) -> BillingGroupsKey:
    figures = tuple(
        dataclasses.replace(
            h,
            figures=tuple(KeyFigure(f.label, f.value + 1000) if f.value == Decimal("290.25") else f for f in h.figures),
        )
        for h in key.household_figures
    )
    return dataclasses.replace(key, household_figures=figures)


def _another_agreement(key: BillingGroupsKey) -> BillingGroupsKey:
    return dataclasses.replace(
        key, contradictions=tuple(dataclasses.replace(c, agreement_id="AGR-4821-9") for c in key.contradictions)
    )


def _no_contradiction(key: BillingGroupsKey) -> BillingGroupsKey:
    return dataclasses.replace(key, contradictions=())


def _the_twin_too(key: BillingGroupsKey) -> BillingGroupsKey:
    twin = Contradiction("HH-7350", "AGR-7350-2", date(2020, 2, 3), ("SYN-73500003",), ("BG-7350-2",))
    return dataclasses.replace(key, contradictions=(*key.contradictions, twin))


def test_the_clean_answer_passes_against_the_key(book: Path, workspace: Path) -> None:
    result = grade(_answer(), billing_groups_key(book, AS_OF), workspace)
    assert (result.score, result.critical_fail, result.passed) == (100, None, True)


@pytest.mark.parametrize(
    ("mutate", "failed"),
    [
        (_no_contradiction, "none_wrongly_named"),
        (_the_twin_too, "none_missed"),
    ],
    ids=["the household cleared", "a household added"],
)
def test_an_altered_set_fails_the_clean_answer(
    book: Path, workspace: Path, mutate: Callable[[BillingGroupsKey], BillingGroupsKey], failed: str
) -> None:
    result = grade(_answer(), mutate(billing_groups_key(book, AS_OF)), workspace)
    assert next(c for c in result.breakdown if c.name == failed).earned == 0
    assert not result.passed


def test_an_altered_figure_fails_the_clean_answer_as_fabricated(book: Path, workspace: Path) -> None:
    result = grade(_answer(), _without_overbilling(billing_groups_key(book, AS_OF)), workspace)
    assert result.critical_fail is not None and "290.25" in result.critical_fail
    assert (result.score, result.passed) == (0, False)


def test_altered_evidence_marks_the_clean_answer_down(book: Path, workspace: Path) -> None:
    # The evidence is not essential: the set is the answer. It costs its 20 points.
    result = grade(_answer(), _another_agreement(billing_groups_key(book, AS_OF)), workspace)
    assert next(c for c in result.breakdown if c.name == "evidence").earned == 0
    assert result.score == 80
