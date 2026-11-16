"""The whitelisted event union, and its parsing at the boundary.

The thirteen events docs/SPEC.md whitelists, plus the opening lots every history starts
from. Any other event type is refused with UnsupportedEventError, naming it.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from casebook.model.dates import parse_date
from casebook.model.files import SYNTHETIC
from casebook.model.money import fmt, parse_decimal


class UnsupportedEventError(ValueError):
    def __init__(self, event_type: str) -> None:
        super().__init__(f"unsupported event {event_type!r}: replay accepts only whitelisted events")
        self.event_type = event_type


class EventFormatError(ValueError):
    pass


@dataclass(frozen=True)
class OpeningLot:
    lot_id: str
    security_id: str
    acquired: dt.date
    units: Decimal
    cost: Decimal


@dataclass(frozen=True)
class Opening:
    event_id: str
    date: dt.date
    account_id: str
    lots: tuple[OpeningLot, ...]
    cash: Decimal


@dataclass(frozen=True)
class Buy:
    event_id: str
    date: dt.date
    settle_date: dt.date
    account_id: str
    security_id: str
    units: Decimal
    price: Decimal
    amount: Decimal


@dataclass(frozen=True)
class Sell:
    event_id: str
    date: dt.date
    settle_date: dt.date
    account_id: str
    security_id: str
    units: Decimal
    price: Decimal
    amount: Decimal


@dataclass(frozen=True)
class Dividend:
    event_id: str
    date: dt.date
    account_id: str
    security_id: str
    units: Decimal
    per_unit: Decimal
    amount: Decimal


@dataclass(frozen=True)
class Contribution:
    event_id: str
    date: dt.date
    account_id: str
    amount: Decimal


@dataclass(frozen=True)
class Withdrawal:
    event_id: str
    date: dt.date
    account_id: str
    amount: Decimal


@dataclass(frozen=True)
class Fee:
    event_id: str
    date: dt.date
    account_id: str
    amount: Decimal
    period_end: dt.date
    billing_group_id: str


@dataclass(frozen=True)
class RequiredDistribution:
    """An RMD: cash out of an IRA. `amount` is the gross, negative; `withheld` is the part sent as tax."""

    event_id: str
    date: dt.date
    account_id: str
    amount: Decimal
    tax_year: int
    withheld: Decimal


@dataclass(frozen=True)
class CharitableDistribution:
    """A QCD: cash out of an IRA straight to a charity. `amount` is negative."""

    event_id: str
    date: dt.date
    account_id: str
    amount: Decimal
    charity: str


@dataclass(frozen=True)
class RothConversion:
    """Cash moved from a traditional IRA (`account_id`) to a Roth IRA; `amount` is the gross, positive."""

    event_id: str
    date: dt.date
    account_id: str
    to_account_id: str
    amount: Decimal


@dataclass(frozen=True)
class Transfer:
    """Units of a security moved in kind, lots keeping their dates and basis; or cash, when `security_id` is None."""

    event_id: str
    date: dt.date
    account_id: str
    to_account_id: str
    security_id: str | None
    units: Decimal
    amount: Decimal


@dataclass(frozen=True)
class Vest:
    """RSU vesting: units arrive with a basis of their value on the vesting date."""

    event_id: str
    date: dt.date
    account_id: str
    security_id: str
    units: Decimal
    price: Decimal


@dataclass(frozen=True)
class Split:
    """A stock split in one account: every lot's units times numerator over denominator, basis unchanged."""

    event_id: str
    date: dt.date
    account_id: str
    security_id: str
    numerator: int
    denominator: int


@dataclass(frozen=True)
class Death:
    """A death: `share` of each lot's basis in the account steps up to its value on the day."""

    event_id: str
    date: dt.date
    account_id: str
    person_id: str
    share: Decimal
    prices: tuple[tuple[str, Decimal], ...]


type Event = (
    Opening
    | Buy
    | Sell
    | Dividend
    | Contribution
    | Withdrawal
    | Fee
    | RequiredDistribution
    | CharitableDistribution
    | RothConversion
    | Transfer
    | Vest
    | Split
    | Death
)

EVENT_TYPES: dict[str, type] = {
    "opening": Opening,
    "buy": Buy,
    "sell": Sell,
    "dividend": Dividend,
    "contribution": Contribution,
    "withdrawal": Withdrawal,
    "fee": Fee,
    "rmd": RequiredDistribution,
    "qcd": CharitableDistribution,
    "roth_conversion": RothConversion,
    "transfer": Transfer,
    "rsu_vest": Vest,
    "split": Split,
    "death": Death,
}
WHITELISTED = tuple(name for name in EVENT_TYPES if name != "opening")
_TYPE_NAMES = {cls: name for name, cls in EVENT_TYPES.items()}


def event_type(event: Event) -> str:
    return _TYPE_NAMES[type(event)]


def settles(event: Event) -> dt.date:
    return event.settle_date if isinstance(event, Buy | Sell) else event.date


def _field(raw: dict[str, Any], name: str) -> Any:
    if name not in raw:
        raise EventFormatError(f"event {raw.get('event_id', '?')} lacks {name!r}")
    return raw[name]


def _date(raw: dict[str, Any], name: str) -> dt.date:
    return parse_date(str(_field(raw, name)))


def _dec(raw: dict[str, Any], name: str) -> Decimal:
    return parse_decimal(str(_field(raw, name)))


def parse_event(raw: dict[str, Any]) -> Event:
    kind = str(raw.get("type", ""))
    if kind not in EVENT_TYPES:
        raise UnsupportedEventError(kind)
    event_id = str(_field(raw, "event_id"))
    day = _date(raw, "date")
    account = str(_field(raw, "account_id"))
    match kind:
        case "opening":
            lots = tuple(
                OpeningLot(
                    lot_id=str(_field(lot, "lot_id")),
                    security_id=str(_field(lot, "security_id")),
                    acquired=_date(lot, "acquired"),
                    units=_dec(lot, "units"),
                    cost=_dec(lot, "cost"),
                )
                for lot in _field(raw, "lots")
            )
            return Opening(event_id, day, account_id=account, lots=lots, cash=_dec(raw, "cash"))
        case "buy" | "sell":
            cls = Buy if kind == "buy" else Sell
            return cls(
                event_id,
                day,
                settle_date=_date(raw, "settle_date"),
                account_id=account,
                security_id=str(_field(raw, "security_id")),
                units=_dec(raw, "units"),
                price=_dec(raw, "price"),
                amount=_dec(raw, "amount"),
            )
        case "dividend":
            return Dividend(
                event_id,
                day,
                account_id=account,
                security_id=str(_field(raw, "security_id")),
                units=_dec(raw, "units"),
                per_unit=_dec(raw, "per_unit"),
                amount=_dec(raw, "amount"),
            )
        case "contribution":
            return Contribution(event_id, day, account_id=account, amount=_dec(raw, "amount"))
        case "withdrawal":
            return Withdrawal(event_id, day, account_id=account, amount=_dec(raw, "amount"))
        case "rmd":
            return RequiredDistribution(
                event_id, day, account, _dec(raw, "amount"), int(_field(raw, "tax_year")), _dec(raw, "withheld")
            )
        case "qcd":
            return CharitableDistribution(event_id, day, account, _dec(raw, "amount"), str(_field(raw, "charity")))
        case "roth_conversion":
            return RothConversion(event_id, day, account, str(_field(raw, "to_account_id")), _dec(raw, "amount"))
        case "transfer":
            security = _field(raw, "security_id")
            return Transfer(
                event_id,
                day,
                account,
                str(_field(raw, "to_account_id")),
                None if security is None else str(security),
                _dec(raw, "units"),
                _dec(raw, "amount"),
            )
        case "rsu_vest":
            return Vest(event_id, day, account, str(_field(raw, "security_id")), _dec(raw, "units"), _dec(raw, "price"))
        case "split":
            return Split(
                event_id,
                day,
                account,
                str(_field(raw, "security_id")),
                int(_field(raw, "numerator")),
                int(_field(raw, "denominator")),
            )
        case "death":
            prices = tuple((str(k), parse_decimal(str(v))) for k, v in sorted(dict(_field(raw, "prices")).items()))
            return Death(event_id, day, account, str(_field(raw, "person_id")), _dec(raw, "share"), prices)
        case _:
            return Fee(
                event_id,
                day,
                account_id=account,
                amount=_dec(raw, "amount"),
                period_end=_date(raw, "period_end"),
                billing_group_id=str(_field(raw, "billing_group_id")),
            )


def event_to_dict(event: Event) -> dict[str, Any]:
    out: dict[str, Any] = {"type": event_type(event)}
    for name, value in vars(event).items():
        if name == "lots":
            out[name] = [
                {
                    "lot_id": lot.lot_id,
                    "security_id": lot.security_id,
                    "acquired": lot.acquired.isoformat(),
                    "units": fmt(lot.units),
                    "cost": fmt(lot.cost),
                }
                for lot in value
            ]
        elif name == "prices":
            out[name] = {security: fmt(price) for security, price in value}
        elif isinstance(value, Decimal):
            out[name] = fmt(value)
        elif isinstance(value, dt.date):
            out[name] = value.isoformat()
        else:
            out[name] = value
    if isinstance(event, Buy | Sell | Vest | Death):
        out["price_label"] = SYNTHETIC
    return out
