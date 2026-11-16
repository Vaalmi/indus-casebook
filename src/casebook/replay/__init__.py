"""The ledger: whitelisted events applied to lots and cash, from the opening lots to the scenario date."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from casebook.model.dates import OPENING_DATE, SCENARIO_DATE
from casebook.model.events import (
    Buy,
    Contribution,
    Dividend,
    Event,
    Fee,
    Opening,
    Sell,
    UnsupportedEventError,
    Withdrawal,
    event_type,
)
from casebook.model.money import cents

__all__ = [
    "ClosedLot",
    "Ledger",
    "Lot",
    "OpeningDateError",
    "OversoldError",
    "ReplayError",
    "ReplayResult",
    "Snapshot",
    "UnsupportedEventError",
    "replay",
]

ZERO = Decimal(0)


class ReplayError(ValueError):
    pass


class OpeningDateError(ReplayError):
    pass


class OversoldError(ReplayError):
    pass


@dataclass(frozen=True)
class Lot:
    lot_id: str
    account_id: str
    security_id: str
    acquired: date
    units: Decimal
    cost: Decimal


@dataclass(frozen=True)
class ClosedLot:
    lot_id: str
    account_id: str
    security_id: str
    acquired: date
    sold: date
    units: Decimal
    cost: Decimal
    proceeds: Decimal


@dataclass(frozen=True)
class Snapshot:
    day: date
    lots: tuple[Lot, ...]
    settled_cash: dict[str, Decimal]
    unsettled_cash: dict[str, Decimal]

    def units(self, account_id: str, security_id: str) -> Decimal:
        return sum(
            (lot.units for lot in self.lots if (lot.account_id, lot.security_id) == (account_id, security_id)),
            ZERO,
        )

    def holdings(self, account_id: str) -> dict[str, Decimal]:
        held: dict[str, Decimal] = {}
        for lot in self.lots:
            if lot.account_id == account_id:
                held[lot.security_id] = held.get(lot.security_id, ZERO) + lot.units
        return dict(sorted(held.items()))


class Ledger:
    def __init__(self) -> None:
        self._lots: list[Lot] = []
        self._settled: dict[str, Decimal] = {}
        self._pending: list[tuple[date, str, Decimal]] = []
        self._day = OPENING_DATE
        self.closed: list[ClosedLot] = []

    def _require_open(self, event: Event) -> None:
        if event.account_id not in self._settled:
            raise ReplayError(f"event {event.event_id}: account {event.account_id} has no opening lots")

    def apply(self, event: Event) -> None:
        if isinstance(event, Opening) and event.date != OPENING_DATE:
            raise OpeningDateError(f"opening lots for {event.account_id} are dated {event.date}, not {OPENING_DATE}")
        if event.date < self._day:
            raise ReplayError(f"event {event.event_id} on {event.date} is earlier than {self._day}")
        if event.date > SCENARIO_DATE:
            raise ReplayError(f"event {event.event_id} on {event.date} is after the scenario date")
        self.settle_through(event.date)
        self._day = event.date
        match event:
            case Opening():
                if event.account_id in self._settled:
                    raise ReplayError(f"account {event.account_id} is opened twice")
                self._settled[event.account_id] = event.cash
                self._lots += [
                    Lot(lot.lot_id, event.account_id, lot.security_id, lot.acquired, lot.units, lot.cost)
                    for lot in event.lots
                ]
            case Buy():
                self._require_open(event)
                self._lots.append(
                    Lot(
                        f"L-{event.event_id}",
                        event.account_id,
                        event.security_id,
                        event.date,
                        event.units,
                        -event.amount,
                    )
                )
                self._pending.append((event.settle_date, event.account_id, event.amount))
            case Sell():
                self._require_open(event)
                self._relieve(event)
                self._pending.append((event.settle_date, event.account_id, event.amount))
            case Dividend() | Contribution() | Withdrawal() | Fee():
                self._require_open(event)
                self._settled[event.account_id] += event.amount
            case _:  # pragma: no cover - the type union makes this unreachable
                raise UnsupportedEventError(event_type(event))

    def _relieve(self, sale: Sell) -> None:
        held = sorted(
            (lot for lot in self._lots if (lot.account_id, lot.security_id) == (sale.account_id, sale.security_id)),
            key=lambda lot: (lot.acquired, lot.lot_id),
        )
        if sum((lot.units for lot in held), ZERO) < sale.units:
            raise OversoldError(
                f"event {sale.event_id} sells {sale.units} of {sale.security_id} in {sale.account_id}, "
                f"more than the {sum((lot.units for lot in held), ZERO)} held"
            )
        remaining = sale.units
        for lot in held:
            if remaining == 0:
                break
            take = min(lot.units, remaining)
            cost = lot.cost if take == lot.units else cents(lot.cost * take / lot.units)
            proceeds = cents(sale.amount * take / sale.units)
            self.closed.append(
                ClosedLot(lot.lot_id, lot.account_id, lot.security_id, lot.acquired, sale.date, take, cost, proceeds)
            )
            index = self._lots.index(lot)
            if take == lot.units:
                del self._lots[index]
            else:
                self._lots[index] = replace(lot, units=lot.units - take, cost=lot.cost - cost)
            remaining -= take

    def settle_through(self, day: date) -> None:
        still: list[tuple[date, str, Decimal]] = []
        for settle, account, amount in self._pending:
            if settle <= day:
                self._settled[account] += amount
            else:
                still.append((settle, account, amount))
        self._pending = still

    def snapshot(self, day: date) -> Snapshot:
        self.settle_through(day)
        unsettled = {account: ZERO for account in self._settled}
        for _, account, amount in self._pending:
            unsettled[account] += amount
        return Snapshot(day, tuple(self._lots), dict(self._settled), unsettled)


@dataclass(frozen=True)
class ReplayResult:
    opening: Snapshot
    snapshots: dict[date, Snapshot]
    closed: tuple[ClosedLot, ...]


def replay(events: Sequence[Event], days: Iterable[date]) -> ReplayResult:
    """Replay the event log and take a snapshot at the end of each requested day.

    `opening` is the state the opening lots describe: the prior 31 December balance.
    """
    wanted = sorted(set(days))
    if any(day < OPENING_DATE or day > SCENARIO_DATE for day in wanted):
        raise ReplayError(f"snapshot days must fall from {OPENING_DATE} to {SCENARIO_DATE}")
    openings = [e for e in events if isinstance(e, Opening)]
    if not openings or list(events[: len(openings)]) != openings:
        raise ReplayError("the event log must begin with the opening lots of every account")
    ledger = Ledger()
    for event in openings:
        ledger.apply(event)
    opening = ledger.snapshot(OPENING_DATE)
    snapshots: dict[date, Snapshot] = {}
    for event in events[len(openings) :]:
        while wanted and wanted[0] < event.date:
            day = wanted.pop(0)
            snapshots[day] = ledger.snapshot(day)
        ledger.apply(event)
    for day in wanted:
        snapshots[day] = ledger.snapshot(day)
    return ReplayResult(opening, snapshots, tuple(ledger.closed))
