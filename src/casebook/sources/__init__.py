"""The four source sets a household's evidence is spread across."""

from casebook.generate.notes import Notes
from casebook.generate.script import HouseholdScript
from casebook.model.events import Event
from casebook.model.files import household_dir
from casebook.replay import ReplayResult
from casebook.securities.market import Market
from casebook.securities.master import Security, by_id
from casebook.sources import crm, custodian, documents, portfolio
from casebook.sources.context import EmitContext


def emit_household(
    script: HouseholdScript,
    events: tuple[Event, ...],
    replayed: ReplayResult,
    market: Market,
    master: tuple[Security, ...],
    real_tickers: bool = False,
    notes: Notes | None = None,
) -> dict[str, bytes]:
    context = EmitContext(script, events, replayed, market, by_id(master), real_tickers, notes)
    root = household_dir(script.household.household_id)
    files: dict[str, bytes] = {}
    for emitter in (custodian.emit, portfolio.emit, crm.emit, documents.emit):
        for relative, content in emitter(context).items():
            files[f"{root}/{relative}"] = content
    return files
