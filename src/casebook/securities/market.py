"""The synthetic market: invented daily prices and dividends, labelled "synthetic".

Integer draws and Decimal arithmetic only, so every platform produces the same prices.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from casebook.model.dates import PRIOR_YEAR_END, SCENARIO_DATE, is_weekday, weekdays
from casebook.model.money import CENT, cents, per_unit
from casebook.securities.master import Security
from casebook.seeding import derive_rng

DIVIDEND_MONTHS = ((2025, 3), (2025, 6), (2025, 9), (2025, 12), (2026, 3))
DIVIDEND_DAY = 25


class NoPriceError(KeyError):
    pass


@dataclass(frozen=True)
class DividendRate:
    security_id: str
    pay_date: date
    per_unit: Decimal


@dataclass(frozen=True)
class Market:
    prices: dict[tuple[str, date], Decimal]
    dividends: tuple[DividendRate, ...]

    def price(self, security_id: str, day: date) -> Decimal:
        try:
            return self.prices[(security_id, day)]
        except KeyError:
            raise NoPriceError(f"no synthetic price for {security_id} on {day}") from None

    def days(self) -> list[date]:
        return sorted({day for _, day in self.prices})


def _pay_date(year: int, month: int) -> date:
    day = date(year, month, DIVIDEND_DAY)
    while not is_weekday(day):
        day = date(year, month, day.day - 1)
    return day


def build_market(master: tuple[Security, ...], seed: int) -> Market:
    """Prices and dividends from the seed and the security alone: a new version re-draws nothing
    (the owner's decision of 16 November 2026, docs/decisions/2026-11-16-version-in-the-price-seed.md)."""
    prices: dict[tuple[str, date], Decimal] = {}
    dividends: list[DividendRate] = []
    days = weekdays(PRIOR_YEAR_END, SCENARIO_DATE)
    for security in master:
        rng = derive_rng("prices", seed, security.internal_id)
        price = Decimal(rng.randint(2000, 40000)) / 100
        for index, day in enumerate(days):
            if index:
                change = Decimal(rng.randint(-90, 94))
                price = max(cents(price * (10000 + change) / 10000), CENT * 100)
            prices[(security.internal_id, day)] = price
        rng = derive_rng("dividends", seed, security.internal_id)
        quarterly_bps = rng.randint(0, 60)
        if quarterly_bps < 10:
            continue
        for year, month in DIVIDEND_MONTHS:
            pay = _pay_date(year, month)
            rate = per_unit(prices[(security.internal_id, pay)] * quarterly_bps / 10000)
            dividends.append(DividendRate(security.internal_id, pay, rate))
    return Market(prices=prices, dividends=tuple(dividends))
