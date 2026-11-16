"""How each event shows in the custodian's transaction file: one row per account it touches."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from casebook.model.events import (
    Buy,
    CharitableDistribution,
    Contribution,
    Death,
    Dividend,
    Event,
    Fee,
    Opening,
    RequiredDistribution,
    RothConversion,
    Sell,
    Split,
    Transfer,
    Vest,
    Withdrawal,
    lot_id,
    transaction_id,
)
from casebook.model.files import (
    BUY,
    CONTRIBUTION,
    CONVERSION_IN,
    CONVERSION_OUT,
    DISTRIBUTION,
    DIVIDEND,
    FEE,
    QCD,
    RSU_VEST,
    SELL,
    SPLIT,
    STEP_UP,
    TRANSFER_IN,
    TRANSFER_OUT,
    WITHDRAWAL,
)
from casebook.model.money import fmt, usd
from casebook.sources.context import EmitContext

ZERO = Decimal(0)


@dataclass(frozen=True)
class TransactionRow:
    transaction_id: str
    account_id: str
    trade_date: date
    settle_date: date
    kind: str
    security_id: str | None
    units: Decimal | None
    lot_id: str
    price: Decimal | None
    amount: Decimal
    description: str


def _row(
    event: Event,
    account: str,
    kind: str,
    amount: Decimal,
    description: str,
    security_id: str | None = None,
    units: Decimal | None = None,
    lot: str = "",
    price: Decimal | None = None,
) -> TransactionRow:
    settle = event.settle_date if isinstance(event, Buy | Sell) else event.date
    return TransactionRow(
        transaction_id(event.event_id),
        account,
        event.date,
        settle,
        kind,
        security_id,
        units,
        lot,
        price,
        amount,
        description,
    )


def rows_for(context: EmitContext, event: Event) -> list[TransactionRow]:
    name = context.label
    match event:
        case Opening():
            return []
        case Buy():
            text = f"Buy {fmt(event.units)} {name(event.security_id)}"
            lot = lot_id(event.event_id)
            return [
                _row(event, event.account_id, BUY, event.amount, text, event.security_id, event.units, lot, event.price)
            ]
        case Sell():
            text = f"Sell {fmt(event.units)} {name(event.security_id)}"
            return [
                _row(
                    event, event.account_id, SELL, event.amount, text, event.security_id, event.units, price=event.price
                )
            ]
        case Dividend():
            text = f"Dividend {name(event.security_id)}, {fmt(event.per_unit)} per unit"
            return [
                _row(
                    event,
                    event.account_id,
                    DIVIDEND,
                    event.amount,
                    text,
                    security_id=event.security_id,
                    units=event.units,
                )
            ]
        case Contribution():
            return [_row(event, event.account_id, CONTRIBUTION, event.amount, "Contribution")]
        case Withdrawal():
            return [_row(event, event.account_id, WITHDRAWAL, event.amount, "Withdrawal")]
        case Fee():
            return [
                _row(
                    event,
                    event.account_id,
                    FEE,
                    event.amount,
                    f"Advisory fee, quarter to {event.period_end.isoformat()}",
                )
            ]
        case RequiredDistribution():
            text = f"Required minimum distribution for {event.tax_year}, {usd(event.withheld)} federal tax withheld"
            return [_row(event, event.account_id, DISTRIBUTION, event.amount, text)]
        case CharitableDistribution():
            return [
                _row(
                    event, event.account_id, QCD, event.amount, f"Qualified charitable distribution to {event.charity}"
                )
            ]
        case RothConversion():
            return [
                _row(
                    event, event.account_id, CONVERSION_OUT, -event.amount, f"Roth conversion to {event.to_account_id}"
                ),
                _row(
                    event, event.to_account_id, CONVERSION_IN, event.amount, f"Roth conversion from {event.account_id}"
                ),
            ]
        case Transfer():
            if event.security_id is None:
                return [
                    _row(
                        event, event.account_id, TRANSFER_OUT, -event.amount, f"Cash transfer to {event.to_account_id}"
                    ),
                    _row(
                        event, event.to_account_id, TRANSFER_IN, event.amount, f"Cash transfer from {event.account_id}"
                    ),
                ]
            text = f"{fmt(event.units)} {name(event.security_id)} in kind"
            out, into = f"Transfer of {text} to {event.to_account_id}", f"Transfer of {text} from {event.account_id}"
            return [
                _row(event, event.account_id, TRANSFER_OUT, ZERO, out, event.security_id, event.units),
                _row(event, event.to_account_id, TRANSFER_IN, ZERO, into, event.security_id, event.units),
            ]
        case Vest():
            lot = lot_id(event.event_id)
            if event.price == ZERO:
                # A custodian that was never given the vesting's value holds the shares with no basis.
                text = f"RSU vesting, {fmt(event.units)} {name(event.security_id)}, no cost basis"
                return [_row(event, event.account_id, RSU_VEST, ZERO, text, event.security_id, event.units, lot)]
            text = f"RSU vesting, {fmt(event.units)} {name(event.security_id)} at {fmt(event.price)}"
            return [
                _row(event, event.account_id, RSU_VEST, ZERO, text, event.security_id, event.units, lot, event.price)
            ]
        case Split():
            added = context.replayed.split_units[event.event_id]
            text = f"{event.numerator}-for-{event.denominator} split of {name(event.security_id)}"
            return [_row(event, event.account_id, SPLIT, ZERO, text, security_id=event.security_id, units=added)]
        case Death():
            person = context.script.household.person(event.person_id).name
            return [
                _row(
                    event,
                    event.account_id,
                    STEP_UP,
                    ZERO,
                    f"Basis step-up on the death of {person}, share {fmt(event.share)}",
                )
            ]


def transaction_rows(context: EmitContext) -> list[TransactionRow]:
    return [row for event in context.events for row in rows_for(context, event)]
