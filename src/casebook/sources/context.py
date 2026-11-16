"""What every emitter is given: the script, its event log, the replayed ledger and the market."""

from dataclasses import dataclass

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

    def label(self, security_id: str) -> str:
        """The name a security appears under in a default build: its alias."""
        return self.securities[security_id].alias
