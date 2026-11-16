"""Money is Decimal, rounded half-up to the cent. The rounding is declared here only."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
PER_UNIT = Decimal("0.0001")


class MoneyFormatError(ValueError):
    pass


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def per_unit(value: Decimal) -> Decimal:
    return value.quantize(PER_UNIT, rounding=ROUND_HALF_UP)


def parse_decimal(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation as error:
        raise MoneyFormatError(f"not a decimal: {text!r}") from error
    if not value.is_finite():
        raise MoneyFormatError(f"not a finite decimal: {text!r}")
    return value


def fmt(value: Decimal) -> str:
    """Plain decimal text, never scientific notation."""
    return format(value, "f")


def usd(value: Decimal) -> str:
    """Dollars for people to read: $1,234.56."""
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(cents(value)):,.2f}"
