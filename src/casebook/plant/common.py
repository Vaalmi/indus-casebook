"""What every planter is given and returns."""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from casebook.generate.billing import QuarterBilling
from casebook.generate.script import HouseholdScript
from casebook.model.dates import PRIOR_YEAR_END
from casebook.model.events import Event
from casebook.model.household import Household
from casebook.model.money import cents
from casebook.model.registry import RegistryEntry
from casebook.replay import ReplayResult, Snapshot
from casebook.securities.market import Market
from casebook.securities.master import Security, by_id, load_master

ZERO = Decimal(0)


class PlantError(ValueError):
    """The situation a script claims does not hold, so the build refuses it."""


@dataclass(frozen=True)
class PlantContext:
    script: HouseholdScript
    # What happened: the sealed event log, and the ledger replayed from it.
    events: tuple[Event, ...]
    replayed: ReplayResult
    quarters: tuple[QuarterBilling, ...]
    market: Market
    # How the book names a security: its alias, or its real ticker in a real-ticker build.
    securities: dict[str, Security] | None = None
    real_tickers: bool = False

    def label(self, security_id: str) -> str:
        security = (self.securities or by_id(load_master()))[security_id]
        return security.real_ticker if self.real_tickers else security.alias

    def value(self, account_id: str, day: date) -> Decimal:
        """An account's value on a snapshot day (a quarter end, the prior 31 December or the scenario date)."""
        return account_value(self.snapshot(day), account_id, self.market)

    def snapshot(self, day: date) -> Snapshot:
        """The ledger at the end of a snapshot day. The opening lots are the prior 31 December's
        balance, valued at that day's prices."""
        if day in (PRIOR_YEAR_END, self.replayed.opening.day):
            return replace(self.replayed.opening, day=PRIOR_YEAR_END)
        return self.replayed.snapshots[day]


@dataclass(frozen=True)
class Planting:
    entries: tuple[RegistryEntry, ...] = ()
    # The events as the custodian recorded them, where the planted item makes its records differ
    # from what happened (a distribution it coded otherwise, a step-up it never booked). None when
    # its records are the event log itself. The build checks the two leave every account's units
    # and cash the same, so only what the custodian says about them differs.
    custodian_events: tuple[Event, ...] | None = None


def account_value(snapshot: Snapshot, account_id: str, market: Market) -> Decimal:
    positions = sum(
        (cents(units * market.price(sid, snapshot.day)) for sid, units in snapshot.holdings(account_id).items()),
        ZERO,
    )
    return positions + snapshot.settled_cash[account_id] + snapshot.unsettled_cash[account_id]


def names(household: Household, person_ids: tuple[str, ...]) -> str:
    listed = [household.person(p).name for p in person_ids]
    return listed[0] if len(listed) == 1 else ", ".join(listed[:-1]) + " and " + listed[-1]
