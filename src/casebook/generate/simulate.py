"""Turn a household script and the synthetic market into its event log, day by day.

Dividends and fees depend on what is held, so the simulation keeps a ledger as it goes.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, Decimal

from casebook.generate.billing import QuarterBilling, bill_quarter
from casebook.generate.script import HouseholdScript
from casebook.model.dates import OPENING_DATE, PRIOR_YEAR_END, QUARTER_ENDS, SCENARIO_DATE, add_weekdays
from casebook.model.events import (
    Buy,
    Contribution,
    Dividend,
    Event,
    Fee,
    Opening,
    OpeningLot,
    Sell,
    Withdrawal,
)
from casebook.model.money import cents
from casebook.replay import Ledger, Snapshot
from casebook.securities.market import Market

SETTLEMENT_DAYS = 1
FEE_DAYS_AFTER_QUARTER = 2
ZERO = Decimal(0)


@dataclass(frozen=True)
class Simulation:
    events: tuple[Event, ...]
    quarters: tuple[QuarterBilling, ...]


def account_value(snapshot: Snapshot, account_id: str, market: Market) -> Decimal:
    positions = sum(
        (cents(units * market.price(sid, snapshot.day)) for sid, units in snapshot.holdings(account_id).items()),
        ZERO,
    )
    return positions + snapshot.settled_cash[account_id] + snapshot.unsettled_cash[account_id]


class _Ids:
    def __init__(self, household_id: str) -> None:
        self._prefix = household_id.removeprefix("HH-")
        self._next = 0

    def __call__(self) -> str:
        self._next += 1
        return f"E-{self._prefix}-{self._next:04d}"


def simulate(script: HouseholdScript, market: Market) -> Simulation:
    hh = script.household
    next_id = _Ids(hh.household_id)
    events: list[Event] = []
    ledger = Ledger()

    def record(event: Event) -> None:
        ledger.apply(event)
        events.append(event)

    for account in script.accounts:
        lots: list[OpeningLot] = []
        for holding in account.holdings:
            price = market.price(holding.security_id, PRIOR_YEAR_END)
            units = (holding.value / price).quantize(Decimal(1), rounding=ROUND_FLOOR)
            cost = cents(units * price * holding.basis_pct / 100)
            lots.append(OpeningLot(holding.lot_id, holding.security_id, holding.acquired, units, cost))
        record(Opening(next_id(), OPENING_DATE, account.account_id, tuple(lots), account.cash))

    fee_dates = {add_weekdays(q, FEE_DAYS_AFTER_QUARTER): q for q in QUARTER_ENDS}
    dividend_days = {d.pay_date for d in market.dividends}
    days = sorted(
        {a.day for a in script.activity}
        | dividend_days
        | set(QUARTER_ENDS)
        | {d for d in fee_dates if d <= SCENARIO_DATE}
    )
    quarter_values: dict[date, dict[str, Decimal]] = {}
    quarters: list[QuarterBilling] = []
    account_ids = [a.account_id for a in script.accounts]

    for day in days:
        held = ledger.snapshot(day)
        for rate in sorted((d for d in market.dividends if d.pay_date == day), key=lambda d: d.security_id):
            for account_id in account_ids:
                units = held.units(account_id, rate.security_id)
                if units > 0:
                    amount = cents(units * rate.per_unit)
                    record(Dividend(next_id(), day, account_id, rate.security_id, units, rate.per_unit, amount))
        for act in (a for a in script.activity if a.day == day):
            settle = add_weekdays(day, SETTLEMENT_DAYS)
            if act.kind in ("buy", "sell"):
                assert act.security_id is not None and act.units is not None
                price = market.price(act.security_id, day)
                gross = cents(act.units * price)
                cls = Buy if act.kind == "buy" else Sell
                amount = -gross if act.kind == "buy" else gross
                record(cls(next_id(), day, settle, act.account_id, act.security_id, act.units, price, amount))
            else:
                assert act.amount is not None
                if act.kind == "contribution":
                    record(Contribution(next_id(), day, act.account_id, act.amount))
                else:
                    record(Withdrawal(next_id(), day, act.account_id, -act.amount))
        if day in fee_dates:
            quarter_end = fee_dates[day]
            billing = bill_quarter(hh, quarter_end, day, quarter_values[quarter_end])
            quarters.append(billing)
            for group in hh.billing_groups:
                for account_id in group.account_ids:
                    fee = billing.account_fees[account_id]
                    record(Fee(next_id(), day, account_id, -fee, quarter_end, group.billing_group_id))
        if day in QUARTER_ENDS:
            snapshot = ledger.snapshot(day)
            quarter_values[day] = {a: account_value(snapshot, a, market) for a in account_ids}
    return Simulation(tuple(events), tuple(quarters))
