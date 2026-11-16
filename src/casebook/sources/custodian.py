"""Custodian CSVs: accounts, positions, transactions, tax lots, and settled and unsettled cash."""

from datetime import date

from casebook.model.dates import PRIOR_YEAR_END, SCENARIO_DATE
from casebook.model.events import Buy, Contribution, Dividend, Fee, Opening, Sell, Withdrawal
from casebook.model.files import (
    ACCOUNTS_COLUMNS,
    ACCOUNTS_CSV,
    BUY,
    CASH_COLUMNS,
    CASH_CSV,
    CONTRIBUTION,
    DIVIDEND,
    FEE,
    POSITIONS_COLUMNS,
    POSITIONS_CSV,
    SELL,
    SYNTHETIC,
    TAX_LOTS_COLUMNS,
    TAX_LOTS_CSV,
    TRANSACTIONS_COLUMNS,
    TRANSACTIONS_CSV,
    WITHDRAWAL,
    csv_text,
)
from casebook.model.money import cents, fmt
from casebook.replay import Snapshot
from casebook.sources.context import SNAPSHOT_DAYS, EmitContext


def _snapshots(context: EmitContext) -> list[tuple[date, Snapshot]]:
    """The prior 31 December balance, then each quarter end and the scenario date."""
    return [(PRIOR_YEAR_END, context.replayed.opening)] + [
        (day, context.replayed.snapshots[day]) for day in SNAPSHOT_DAYS
    ]


def _accounts(context: EmitContext) -> str:
    hh = context.script.household
    rows = [
        {
            "account_id": a.account_id,
            "account_type": a.account_type,
            "registration": a.registration,
            "owners": "; ".join(hh.person(p).name for p in hh.owners(a.account_id)),
            "opened": a.opened.isoformat(),
            "valuation_date": SCENARIO_DATE.isoformat(),
            "known_as_of": SCENARIO_DATE.isoformat(),
        }
        for a in hh.accounts
    ]
    return csv_text(ACCOUNTS_COLUMNS, rows)


def _positions(context: EmitContext) -> str:
    rows: list[dict[str, str]] = []
    for day, snapshot in _snapshots(context):
        for account in context.script.household.accounts:
            for security_id, units in snapshot.holdings(account.account_id).items():
                price = context.market.price(security_id, day)
                rows.append(
                    {
                        "account_id": account.account_id,
                        "security_id": security_id,
                        "security": context.label(security_id),
                        "units": fmt(units),
                        "price": fmt(price),
                        "price_label": SYNTHETIC,
                        "market_value": fmt(cents(units * price)),
                        "valuation_date": day.isoformat(),
                        "known_as_of": day.isoformat(),
                    }
                )
    return csv_text(POSITIONS_COLUMNS, rows)


def describe(context: EmitContext, event: object) -> tuple[str, str]:
    """The custodian's transaction type and description for an event."""
    match event:
        case Buy():
            return BUY, f"Buy {fmt(event.units)} {context.label(event.security_id)}"
        case Sell():
            return SELL, f"Sell {fmt(event.units)} {context.label(event.security_id)}"
        case Dividend():
            return DIVIDEND, f"Dividend {context.label(event.security_id)}, {fmt(event.per_unit)} per unit"
        case Contribution():
            return CONTRIBUTION, "Contribution"
        case Withdrawal():
            return WITHDRAWAL, "Withdrawal"
        case Fee():
            return FEE, f"Advisory fee, quarter to {event.period_end.isoformat()}"
        case _:
            raise TypeError(f"no transaction for {event!r}")


def transaction_id(event_id: str) -> str:
    return "T" + event_id.removeprefix("E")


def _transactions(context: EmitContext) -> str:
    rows: list[dict[str, str]] = []
    for event in context.events:
        if isinstance(event, Opening):
            continue
        kind, description = describe(context, event)
        trade = isinstance(event, Buy | Sell)
        has_security = isinstance(event, Buy | Sell | Dividend)
        rows.append(
            {
                "transaction_id": transaction_id(event.event_id),
                "account_id": event.account_id,
                "trade_date": event.date.isoformat(),
                "settle_date": (event.settle_date if isinstance(event, Buy | Sell) else event.date).isoformat(),
                "type": kind,
                "security_id": event.security_id if has_security else "",
                "security": context.label(event.security_id) if has_security else "",
                "units": fmt(event.units) if has_security else "",
                "price": fmt(event.price) if trade else "",
                "price_label": SYNTHETIC if trade else "",
                "amount": fmt(event.amount),
                "description": description,
                "valuation_date": event.date.isoformat(),
                "known_as_of": event.date.isoformat(),
            }
        )
    return csv_text(TRANSACTIONS_COLUMNS, rows)


def _tax_lots(context: EmitContext) -> str:
    final = context.replayed.snapshots[SCENARIO_DATE]
    lots = sorted(final.lots, key=lambda lot: (lot.account_id, lot.security_id, lot.acquired, lot.lot_id))
    rows = [
        {
            "account_id": lot.account_id,
            "lot_id": lot.lot_id,
            "security_id": lot.security_id,
            "security": context.label(lot.security_id),
            "acquired_date": lot.acquired.isoformat(),
            "units": fmt(lot.units),
            "cost_basis": fmt(lot.cost),
            "valuation_date": SCENARIO_DATE.isoformat(),
            "known_as_of": SCENARIO_DATE.isoformat(),
        }
        for lot in lots
    ]
    return csv_text(TAX_LOTS_COLUMNS, rows)


def _cash(context: EmitContext) -> str:
    rows = [
        {
            "account_id": account.account_id,
            "settled_cash": fmt(cents(snapshot.settled_cash[account.account_id])),
            "unsettled_cash": fmt(cents(snapshot.unsettled_cash[account.account_id])),
            "valuation_date": day.isoformat(),
            "known_as_of": day.isoformat(),
        }
        for day, snapshot in _snapshots(context)
        for account in context.script.household.accounts
    ]
    return csv_text(CASH_COLUMNS, rows)


def emit(context: EmitContext) -> dict[str, bytes]:
    return {
        ACCOUNTS_CSV: _accounts(context).encode(),
        POSITIONS_CSV: _positions(context).encode(),
        TRANSACTIONS_CSV: _transactions(context).encode(),
        TAX_LOTS_CSV: _tax_lots(context).encode(),
        CASH_CSV: _cash(context).encode(),
    }
