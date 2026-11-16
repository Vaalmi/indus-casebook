"""One price per ticker per date; value equals units times that price under the declared rounding."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from casebook.checks.book import book_price_rows
from casebook.model.dates import parse_date
from casebook.model.files import (
    BUY,
    PORTFOLIO_POSITIONS,
    POSITIONS_CSV,
    PRICES_CSV,
    SELL,
    TRANSACTIONS_CSV,
    read_json,
    read_positions,
    read_transactions,
)
from casebook.model.money import cents, parse_decimal


def check_prices(root: Path) -> list[str]:
    problems: list[str] = []
    seen: dict[tuple[str, date], tuple[Decimal, str]] = {}

    def note(security: str, day: date, price: Decimal, where: str) -> None:
        first = seen.setdefault((security, day), (price, where))
        if first[0] != price:
            problems.append(f"{where}: {security} on {day} is priced {price}; {first[1]} prices it {first[0]}")

    for security, day, price, line in book_price_rows(root):
        note(security, day, price, f"{PRICES_CSV} line {line}")

    for row in read_positions(root):
        where = f"{POSITIONS_CSV} line {row.line}"
        note(row.security_id, row.valuation_date, row.price, where)
        if row.market_value != cents(row.units * row.price):
            problems.append(
                f"{where}: {row.account_id} {row.security_id} value {row.market_value} is not {row.units} x {row.price}"
            )
    for t in read_transactions(root):
        if t.price is None or t.units is None:
            continue
        where = f"{TRANSACTIONS_CSV} line {t.line}"
        note(t.security_id, t.trade_date, t.price, where)
        gross = cents(t.units * t.price)
        if (t.type == BUY and t.amount != -gross) or (t.type == SELL and t.amount != gross):
            problems.append(f"{where}: {t.transaction_id} amount {t.amount} is not {t.units} x {t.price}")
    for index, item in enumerate(read_json(root, PORTFOLIO_POSITIONS)["positions"]):
        where = f"{PORTFOLIO_POSITIONS} positions[{index}]"
        units, price = parse_decimal(str(item["units"])), parse_decimal(str(item["price"]))
        note(str(item["security_id"]), parse_date(str(item["valuation_date"])), price, where)
        if parse_decimal(str(item["market_value"])) != cents(units * price):
            problems.append(f"{where}: {item['account_id']} {item['security_id']} value is not {units} x {price}")
    return problems
