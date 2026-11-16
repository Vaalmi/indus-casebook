"""What every emitter is given: the script, its event log, the replayed ledger and the market."""

from dataclasses import dataclass

from casebook.generate.notes import Notes
from casebook.generate.script import HouseholdScript
from casebook.model.dates import QUARTER_ENDS, SCENARIO_DATE
from casebook.model.events import Event
from casebook.replay import ReplayResult
from casebook.securities.market import Market
from casebook.securities.master import Security

SNAPSHOT_DAYS = (*QUARTER_ENDS, SCENARIO_DATE)


@dataclass(frozen=True)
class EmitContext:
    script: HouseholdScript
    events: tuple[Event, ...]
    replayed: ReplayResult
    market: Market
    securities: dict[str, Security]
    real_tickers: bool = False
    # The owner's hand-written notes, for a featured household that has them.
    notes: Notes | None = None

    def label(self, security_id: str) -> str:
        """The name a security appears under: its alias, or its real ticker in real-ticker mode."""
        security = self.securities[security_id]
        return security.real_ticker if self.real_tickers else security.alias
