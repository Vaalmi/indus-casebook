from decimal import Decimal

import pytest

from casebook.model.money import MoneyFormatError, cents, parse_decimal, usd


@pytest.mark.parametrize(
    ("value", "expected"),
    [("2.345", "2.35"), ("2.344", "2.34"), ("-2.345", "-2.35"), ("0.005", "0.01"), ("10", "10.00")],
)
def test_cents_round_half_up(value: str, expected: str) -> None:
    assert cents(Decimal(value)) == Decimal(expected)


def test_usd_reads_like_dollars() -> None:
    assert usd(Decimal("1234.5")) == "$1,234.50"
    assert usd(Decimal("-0.5")) == "-$0.50"
    assert usd(Decimal("1000000")) == "$1,000,000.00"


@pytest.mark.parametrize("text", ["abc", "NaN", "Infinity", ""])
def test_parse_decimal_refuses_what_is_not_money(text: str) -> None:
    with pytest.raises(MoneyFormatError):
        parse_decimal(text)
