"""The fee reconciliation key against hand-worked cases and the planted item in the real book."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.keys.fee_reconciliation import UnsettledFeeError, fee_key
from casebook.model.files import (
    CASH_COLUMNS,
    CASH_CSV,
    CRM_JSON,
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

QUARTER_END = date(2026, 3, 31)
A = "SYN-00010001"
B = "SYN-00010002"


def _position(account: str, value: str, day: str) -> dict[str, str]:
    return {
        "account_id": account,
        "security_id": "SEC-0001",
        "security": "Larkspur Total Market Fund",
        "units": "1000",
        "price": str(Decimal(value) / 1000),
        "price_label": "synthetic",
        "market_value": value,
        "valuation_date": day,
        "known_as_of": day,
    }


def _cash(account: str, day: str) -> dict[str, str]:
    return {
        "account_id": account,
        "settled_cash": "0.00",
        "unsettled_cash": "0.00",
        "valuation_date": day,
        "known_as_of": day,
    }


def _fee(transaction_id: str, account: str, amount: str, day: str, quarter: str) -> dict[str, str]:
    return {
        "transaction_id": transaction_id,
        "account_id": account,
        "trade_date": day,
        "settle_date": day,
        "type": "FEE",
        "security_id": "",
        "security": "",
        "units": "",
        "price": "",
        "price_label": "",
        "amount": amount,
        "description": f"Advisory fee, quarter to {quarter}",
        "valuation_date": day,
        "known_as_of": day,
    }


def _householding(signed: str) -> dict[str, Any]:
    return {
        "agreement_id": "AGR-0001-2",
        "kind": "householding",
        "party_ids": ["P-0001-1"],
        "account_ids": [A, B],
        "signed": signed,
        "summary": "Householding letter: both accounts bill as one group.",
    }


def _household(root: Path, agreements: list[dict[str, Any]], *, fees: bool = True, cash_for_b: bool = True) -> Path:
    """Two accounts worth 600,000 and 500,000 on the quarter end, billed as two groups on one schedule."""
    files = {
        POSITIONS_CSV: csv_text(
            POSITIONS_COLUMNS,
            [
                _position(A, "550000.00", "2025-12-31"),
                _position(A, "600000.00", "2026-03-31"),
                _position(B, "500000.00", "2026-03-31"),
            ],
        ),
        CASH_CSV: csv_text(CASH_COLUMNS, [_cash(A, "2026-03-31")] + ([_cash(B, "2026-03-31")] if cash_for_b else [])),
        TRANSACTIONS_CSV: csv_text(
            TRANSACTIONS_COLUMNS,
            [_fee("T-1", A, "-999.00", "2026-01-02", "2025-12-31")]
            + (
                [
                    _fee("T-2", A, "-1500.00", "2026-04-02", "2026-03-31"),
                    _fee("T-3", B, "-1250.00", "2026-04-02", "2026-03-31"),
                ]
                if fees
                else []
            ),
        ),
        PORTFOLIO_HOUSEHOLD: json_text(
            {
                "household_id": "HH-0001",
                "billing_groups": [
                    {"billing_group_id": "BG-0001-1", "schedule_id": "FS-STD", "account_ids": [A]},
                    {"billing_group_id": "BG-0001-2", "schedule_id": "FS-STD", "account_ids": [B]},
                ],
            }
        ),
        PORTFOLIO_BILLING: json_text(
            {
                "fee_schedules": [
                    {
                        "schedule_id": "FS-STD",
                        "basis": "Quarterly in arrears on positions plus cash",
                        "tiers": [
                            {"up_to": "1000000", "annual_rate": "0.0100"},
                            {"up_to": "2000000", "annual_rate": "0.0080"},
                            {"up_to": None, "annual_rate": "0.0060"},
                        ],
                    }
                ]
            }
        ),
        CRM_JSON: json_text({"agreements": agreements}),
    }
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root


def test_signed_householding_agreement_bills_both_accounts_as_one_group(tmp_path: Path) -> None:
    # (1,000,000 x 1.00% + 100,000 x 0.80%) / 4 = (10,000 + 800) / 4 = 2,700.00 against 2,750.00 debited.
    key = fee_key(_household(tmp_path, [_householding("2025-06-01")]), QUARTER_END)
    assert key.household_id == "HH-0001"
    assert key.fee_date == date(2026, 4, 2)
    assert key.debited_fee == Decimal("2750.00")
    assert key.correct_fee == Decimal("2700.00")
    assert key.amount_misbilled == Decimal("50.00")
    assert key.finding == "fee_error"
    assert [(g.account_ids, g.portfolio_group_ids, g.value) for g in key.billing_groups] == [
        ((A, B), ("BG-0001-1", "BG-0001-2"), Decimal("1100000.00"))
    ]


def test_without_an_agreement_the_portfolio_groups_stand(tmp_path: Path) -> None:
    # 600,000 x 1.00% / 4 = 1,500.00 and 500,000 x 1.00% / 4 = 1,250.00: exactly what was debited.
    key = fee_key(_household(tmp_path, []), QUARTER_END)
    assert key.correct_fee == Decimal("2750.00")
    assert key.amount_misbilled == Decimal("0.00")
    assert key.finding == "no_fee_error"
    assert [g.fee for g in key.billing_groups] == [Decimal("1500.00"), Decimal("1250.00")]


def test_an_agreement_signed_after_the_quarter_end_changes_nothing(tmp_path: Path) -> None:
    key = fee_key(_household(tmp_path, [_householding("2026-04-01")]), QUARTER_END)
    assert key.correct_fee == Decimal("2750.00")
    assert key.finding == "no_fee_error"
    assert len(key.billing_groups) == 2


def test_computed_figures_hold_the_values_and_fees_an_answer_may_work_out(tmp_path: Path) -> None:
    key = fee_key(_household(tmp_path, [_householding("2025-06-01")]), QUARTER_END)
    values = {f.value for f in key.computed_figures}
    for figure in ("600000.00", "500000.00", "1100000.00", "10000", "800", "2700.00", "2750.00", "50.00"):
        assert Decimal(figure) in values


def test_the_key_writes_as_json_with_money_as_strings(tmp_path: Path) -> None:
    data = fee_key(_household(tmp_path, [_householding("2025-06-01")]), QUARTER_END).to_dict()
    assert data["quarter_end"] == "2026-03-31"
    assert data["fee_date"] == "2026-04-02"
    assert (data["debited_fee"], data["correct_fee"], data["amount_misbilled"]) == ("2750.00", "2700.00", "50.00")
    assert data["billing_groups"][0]["account_ids"] == [A, B]
    assert data["billing_groups"][0]["fee"] == "2700.00"
    assert all(isinstance(f["value"], str) for f in data["computed_figures"])


def test_no_fee_rows_for_the_quarter_cannot_be_settled(tmp_path: Path) -> None:
    with pytest.raises(UnsettledFeeError, match="2026-03-31"):
        fee_key(_household(tmp_path, [], fees=False), QUARTER_END)


def test_an_account_with_no_value_on_the_quarter_end_cannot_be_settled(tmp_path: Path) -> None:
    with pytest.raises(UnsettledFeeError, match=B):
        fee_key(_household(tmp_path, [], cash_for_b=False), QUARTER_END)


def test_the_trap_household_was_overbilled_by_the_registry_figure(book: Path) -> None:
    key = fee_key(book / household_dir("HH-4821"), QUARTER_END)
    assert key.finding == "fee_error"
    assert key.amount_misbilled == Decimal("508.56")


def test_the_twin_household_was_billed_correctly(book: Path) -> None:
    assert fee_key(book / household_dir("HH-7350"), QUARTER_END).finding == "no_fee_error"
