"""Custodian CSVs: accounts, positions, transactions, tax lots, beneficiaries, and settled and unsettled cash."""

from datetime import date

from casebook.model.dates import PRIOR_YEAR_END, SCENARIO_DATE
from casebook.model.files import (
    ACCOUNTS_COLUMNS,
    ACCOUNTS_CSV,
    BENEFICIARIES_COLUMNS,
    BENEFICIARIES_CSV,
    CASH_COLUMNS,
    CASH_CSV,
    POSITIONS_COLUMNS,
    POSITIONS_CSV,
    REALIZED_COLUMNS,
    REALIZED_CSV,
    SYNTHETIC,
    TAX_LOTS_COLUMNS,
    TAX_LOTS_CSV,
    TRANSACTIONS_COLUMNS,
    TRANSACTIONS_CSV,
    csv_text,
)
from casebook.model.money import cents, fmt
from casebook.replay import Snapshot
from casebook.sources.context import SNAPSHOT_DAYS, EmitContext
from casebook.sources.transactions import transaction_id, transaction_rows


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


def _transactions(context: EmitContext) -> str:
    rows = [
        {
            "transaction_id": row.transaction_id,
            "account_id": row.account_id,
            "trade_date": row.trade_date.isoformat(),
            "settle_date": row.settle_date.isoformat(),
            "type": row.kind,
            "security_id": row.security_id or "",
            "security": context.label(row.security_id) if row.security_id else "",
            "units": fmt(row.units) if row.units is not None else "",
            "lot_id": row.lot_id,
            "price": fmt(row.price) if row.price is not None else "",
            "price_label": SYNTHETIC if row.price is not None else "",
            "amount": fmt(row.amount),
            "description": row.description,
            "valuation_date": row.trade_date.isoformat(),
            "known_as_of": row.trade_date.isoformat(),
        }
        for row in transaction_rows(context)
    ]
    return csv_text(TRANSACTIONS_COLUMNS, rows)


def _tax_lots(context: EmitContext) -> str:
    """Open lots at the prior 31 December (the opening lots) and on the scenario date."""
    rows: list[dict[str, str]] = []
    for day, snapshot in (
        (PRIOR_YEAR_END, context.replayed.opening),
        (SCENARIO_DATE, context.replayed.snapshots[SCENARIO_DATE]),
    ):
        for lot in sorted(snapshot.lots, key=lambda lot: (lot.account_id, lot.security_id, lot.acquired, lot.lot_id)):
            rows.append(
                {
                    "account_id": lot.account_id,
                    "lot_id": lot.lot_id,
                    "security_id": lot.security_id,
                    "security": context.label(lot.security_id),
                    "acquired_date": lot.acquired.isoformat(),
                    "units": fmt(lot.units),
                    "cost_basis": fmt(lot.cost),
                    "valuation_date": day.isoformat(),
                    "known_as_of": day.isoformat(),
                }
            )
    return csv_text(TAX_LOTS_COLUMNS, rows)


def _realized(context: EmitContext) -> str:
    """Each lot a sale closed, in whole or in part: the custodian's realized gain and loss detail."""
    rows = [
        {
            "transaction_id": transaction_id(closed.event_id),
            "account_id": closed.account_id,
            "lot_id": closed.lot_id,
            "security_id": closed.security_id,
            "security": context.label(closed.security_id),
            "acquired_date": closed.acquired.isoformat(),
            "sold_date": closed.sold.isoformat(),
            "units": fmt(closed.units),
            "cost_basis": fmt(closed.cost),
            "proceeds": fmt(closed.proceeds),
            "gain": fmt(closed.proceeds - closed.cost),
            "valuation_date": closed.sold.isoformat(),
            "known_as_of": closed.sold.isoformat(),
        }
        for closed in context.replayed.closed
    ]
    return csv_text(REALIZED_COLUMNS, rows)


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


def _beneficiaries(context: EmitContext) -> str:
    rows = [
        {
            "account_id": b.account_id,
            "designation": b.designation,
            "name": b.name,
            "relationship": b.relationship,
            "share_percent": fmt(b.share),
            "person_id": b.person_id or "",
            "valuation_date": b.designated.isoformat(),
            "known_as_of": b.designated.isoformat(),
        }
        for b in context.script.household.beneficiaries
    ]
    return csv_text(BENEFICIARIES_COLUMNS, rows)


def emit(context: EmitContext) -> dict[str, bytes]:
    return {
        ACCOUNTS_CSV: _accounts(context).encode(),
        POSITIONS_CSV: _positions(context).encode(),
        TRANSACTIONS_CSV: _transactions(context).encode(),
        TAX_LOTS_CSV: _tax_lots(context).encode(),
        REALIZED_CSV: _realized(context).encode(),
        CASH_CSV: _cash(context).encode(),
        BENEFICIARIES_CSV: _beneficiaries(context).encode(),
    }
