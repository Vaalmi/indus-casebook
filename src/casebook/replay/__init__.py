"""The ledger: whitelisted events applied to lots and cash, from the opening lots to the scenario date."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from casebook.model.dates import OPENING_DATE, SCENARIO_DATE
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
    UnsupportedEventError,
    Vest,
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
    event_id: str
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
        self.split_units: dict[str, Decimal] = {}

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
            case Dividend() | Contribution() | Withdrawal() | Fee() | RequiredDistribution() | CharitableDistribution():
                self._require_open(event)
                self._settled[event.account_id] += event.amount
            case RothConversion():
                self._require_open(event)
                self._require_account(event.event_id, event.to_account_id)
                self._settled[event.account_id] -= event.amount
                self._settled[event.to_account_id] += event.amount
            case Transfer():
                self._require_open(event)
                self._require_account(event.event_id, event.to_account_id)
                if event.security_id is None:
                    self._settled[event.account_id] -= event.amount
                    self._settled[event.to_account_id] += event.amount
                else:
                    self._move(event, event.security_id)
            case Vest():
                self._require_open(event)
                cost = cents(event.units * event.price)
                self._lots.append(
                    Lot(f"L-{event.event_id}", event.account_id, event.security_id, event.date, event.units, cost)
                )
            case Split():
                self._require_open(event)
                ratio = Decimal(event.numerator) / Decimal(event.denominator)
                before = sum((lot.units for lot in self._held(event.account_id, event.security_id)), ZERO)
                self.split_units[event.event_id] = before * ratio - before
                self._lots = [
                    replace(lot, units=lot.units * ratio)
                    if (lot.account_id, lot.security_id) == (event.account_id, event.security_id)
                    else lot
                    for lot in self._lots
                ]
            case Death():
                self._require_open(event)
                self._step_up(event)
            case _:  # pragma: no cover - the type union makes this unreachable
                raise UnsupportedEventError(event_type(event))

    def _require_account(self, event_id: str, account_id: str) -> None:
        if account_id not in self._settled:
            raise ReplayError(f"event {event_id}: account {account_id} has no opening lots")

    def _held(self, account_id: str, security_id: str) -> list[Lot]:
        return sorted(
            (lot for lot in self._lots if (lot.account_id, lot.security_id) == (account_id, security_id)),
            key=lambda lot: (lot.acquired, lot.lot_id),
        )

    def _move(self, transfer: Transfer, security_id: str) -> None:
        """In kind: whole lots keep their IDs; a lot split by the move leaves its moved part as `<lot>/<event>`."""
        held = self._held(transfer.account_id, security_id)
        if sum((lot.units for lot in held), ZERO) < transfer.units:
            raise OversoldError(f"event {transfer.event_id} moves more {security_id} than {transfer.account_id} holds")
        remaining = transfer.units
        for lot in held:
            if remaining == 0:
                break
            take = min(lot.units, remaining)
            index = self._lots.index(lot)
            if take == lot.units:
                self._lots[index] = replace(lot, account_id=transfer.to_account_id)
            else:
                cost = cents(lot.cost * take / lot.units)
                self._lots[index] = replace(lot, units=lot.units - take, cost=lot.cost - cost)
                moved = Lot(
                    f"{lot.lot_id}/{transfer.event_id}", transfer.to_account_id, security_id, lot.acquired, take, cost
                )
                self._lots.append(moved)
            remaining -= take

    def _step_up(self, death: Death) -> None:
        """The stepped part takes the day's value and date; a part not stepped up keeps its lot ID, basis and date."""
        prices = dict(death.prices)
        if not 0 < death.share <= 1:
            raise ReplayError(f"event {death.event_id}: a step-up share is above 0 and at most 1, not {death.share}")
        stepped: list[Lot] = []
        for lot in self._lots:
            if lot.account_id != death.account_id:
                stepped.append(lot)
                continue
            if lot.security_id not in prices:
                raise ReplayError(f"event {death.event_id} gives no value for {lot.security_id}")
            units = lot.units * death.share
            if units == units.to_integral_value():
                units = units.quantize(Decimal(1))  # half of 1,508 units is 754 units, not 754.0
            new = Lot(
                lot.lot_id if death.share == 1 else f"{lot.lot_id}-S",
                lot.account_id,
                lot.security_id,
                death.date,
                units,
                cents(units * prices[lot.security_id]),
            )
            stepped.append(new)
            if death.share < 1:
                kept = lot.cost - cents(lot.cost * death.share)
                stepped.append(replace(lot, units=lot.units - units, cost=kept))
        self._lots = stepped

    def _relieve(self, sale: Sell) -> None:
        held = self._held(sale.account_id, sale.security_id)
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
                ClosedLot(
                    sale.event_id,
                    lot.lot_id,
                    lot.account_id,
                    lot.security_id,
                    lot.acquired,
                    sale.date,
                    take,
                    cost,
                    proceeds,
                )
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
    split_units: dict[str, Decimal]


def overdrawn(result: ReplayResult) -> list[str]:
    """Every account whose cash, settled and unsettled together, is below zero on a snapshot day: an
    overdraft no custodian shows, so a household that has one is refused."""
    found: list[str] = []
    for snapshot in (result.opening, *result.snapshots.values()):
        for account, settled in sorted(snapshot.settled_cash.items()):
            cash = settled + snapshot.unsettled_cash.get(account, ZERO)
            if cash < 0:
                found.append(f"{account} holds {cash} in cash on {snapshot.day}")
    return found


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
    return ReplayResult(opening, snapshots, tuple(ledger.closed), dict(ledger.split_units))
