"""`casebook build`: generate, replay, plant and emit every household, then write the manifest.

The build refuses a household that contradicts the ID ledger, an identifier outside its invalid
range, a real ticker or name in a default build, and two sources that disagree with no registry
entry.
"""

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from casebook import BOOK_VERSION
from casebook.checks.agreement import check_sources_agree
from casebook.generate.background import BackgroundError, generate_background
from casebook.generate.notes import NotesError, check_notes, load_notes, notes_path
from casebook.generate.script import HouseholdScript, load_scripts
from casebook.generate.simulate import simulate
from casebook.model.archetypes import ARCHETYPES, HELD_OUT_ARCHETYPES, frozen
from casebook.model.dates import OPENING_DATE, SCENARIO_DATE
from casebook.model.events import event_to_dict
from casebook.model.files import (
    ALIASES,
    MANIFEST,
    METADATA,
    PRICES_COLUMNS,
    PRICES_CSV,
    REAL_TICKERS,
    REGISTRY,
    SEALED_HOUSEHOLDS,
    SECURITIES_COLUMNS,
    SECURITIES_CSV,
    SYNTHETIC,
    csv_text,
    event_log_path,
    household_dir,
    json_text,
    tax_summary_path,
)
from casebook.model.identifiers import file_problems
from casebook.model.ledger import LedgerError, load_ledger
from casebook.model.money import fmt
from casebook.model.registry import RegistryEntry
from casebook.model.tax import TAX_YEAR, TaxUnitFacts, facts_to_dict, summary_to_dict
from casebook.notice import NOTICE
from casebook.plant import PlantContext, plant
from casebook.published_text import text_of
from casebook.replay import ReplayResult, Snapshot, overdrawn, replay
from casebook.securities.market import Market, build_market
from casebook.securities.master import Security, by_id, load_master
from casebook.securities.scan import default_scan
from casebook.sources import emit_household
from casebook.sources.context import SNAPSHOT_DAYS
from casebook.tax.facts import TaxFactsError, tax_unit_facts
from casebook.tax.summary import TaxReport, tax_report

DATA_LICENCE = "CC-BY-4.0"
REPO = Path(__file__).resolve().parents[2]
ID_LEDGER = REPO / "book" / "id_ledger.json"


class BuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class BuildResult:
    root: Path
    households: tuple[str, ...]
    files: int


def _book_files(master: tuple[Security, ...], market: Market, real_tickers: bool) -> dict[str, bytes]:
    aliases = {s.internal_id: s.real_ticker if real_tickers else s.alias for s in master}
    securities = [{"security_id": sid, "security": name} for sid, name in aliases.items()]
    prices = [
        {
            "security_id": sid,
            "security": aliases[sid],
            "price": fmt(price),
            "price_label": SYNTHETIC,
            # A closing price is known the day it is struck.
            "valuation_date": day.isoformat(),
            "known_as_of": day.isoformat(),
        }
        for (sid, day), price in sorted(market.prices.items())
    ]
    return {
        SECURITIES_CSV: csv_text(SECURITIES_COLUMNS, securities).encode(),
        PRICES_CSV: csv_text(PRICES_COLUMNS, prices).encode(),
    }


def _sealed_household(script: HouseholdScript) -> dict[str, Any]:
    return {
        "household_id": script.household.household_id,
        "archetype": script.household.archetype,
        "archetype_name": ARCHETYPES[script.household.archetype],
        "pair": script.pair,
        "role": script.role,
        "set": "background" if script.background else "featured",
        "twin_kind": script.twin.kind if script.twin else None,
        "explanation": script.twin.explanation if script.twin else None,
        "script": script.source,
    }


def refuse_held_out(scripts: list[HouseholdScript], held_out: bool) -> None:
    """A held-out featured pair stays out of every public build until the freeze."""
    found = sorted(
        s.household.household_id for s in scripts if s.household.archetype in HELD_OUT_ARCHETYPES and not s.background
    )
    if found and not held_out and not frozen():
        raise BuildError(
            f"{', '.join(found)}: the featured pairs for archetypes 7 and 8 are held out until the freeze; "
            "keep their scripts in $CASEBOOK_PRIVATE and build them with --held-out"
        )


def name_real_tickers(files: dict[str, bytes], master: tuple[Security, ...]) -> dict[str, bytes]:
    """A real-ticker build differs from the default only in identifiers: script text that names a
    security by its alias (a CRM record, an employer on a wages line) names it by its ticker too.
    PDFs are drawn with the ticker already."""
    aliases = sorted(master, key=lambda s: len(s.alias), reverse=True)

    def named(text: str) -> str:
        for security in aliases:
            text = text.replace(security.alias, security.real_ticker)
        return text

    return {
        name: named(data.decode("utf-8")).encode("utf-8") if name.endswith((".csv", ".json")) else data
        for name, data in files.items()
    }


def generate_book(
    seed: int,
    scripts_dir: Path,
    real_tickers: bool = False,
    ledger: Path = ID_LEDGER,
    held_out: bool = False,
    background: bool = False,
    extra_scripts: Path | None = None,
    background_archetypes: frozenset[int] | None = None,
) -> dict[str, bytes]:
    master = load_master()
    market = build_market(master, seed)
    folders = [scripts_dir, *([extra_scripts] if extra_scripts else [])]
    found = [(folder, script) for folder in folders for script in load_scripts(folder)]
    if not found and not background:
        raise BuildError(f"no household scripts under {scripts_dir}")
    refuse_held_out([script for _, script in found], held_out)
    if background:
        try:
            found += [(scripts_dir, script) for script in generate_background(seed, market, background_archetypes)]
        except BackgroundError as error:
            raise BuildError(str(error)) from error
    found.sort(key=lambda pair: pair[1].household.household_id)
    ids = [script.household.household_id for _, script in found]
    if len(set(ids)) != len(ids):
        raise BuildError("two households share an ID")
    scripts = [script for _, script in found]
    try:
        published = load_ledger(ledger)
        for script in scripts:
            hh = script.household
            published.check_household(hh.household_id, hh.archetype, script.pair, script.role)
    except LedgerError as error:
        raise BuildError(str(error)) from error
    files = _book_files(master, market, real_tickers)
    entries: list[RegistryEntry] = []
    units: list[TaxUnitFacts] = []
    for folder, script in found:
        simulation = simulate(script, market)
        replayed = replay(simulation.events, SNAPSHOT_DAYS)
        overdrafts = overdrawn(replayed)
        if overdrafts:
            raise BuildError(f"{script.household.household_id}: {'; '.join(overdrafts)}")
        planting = plant(
            PlantContext(script, simulation.events, replayed, simulation.quarters, market, by_id(master), real_tickers)
        )
        entries += planting.entries
        # The custodian's files, its statements and the portfolio system it feeds show the events
        # as the custodian recorded them; the sealed log keeps what happened.
        recorded, recorded_ledger = simulation.events, replayed
        if planting.custodian_events is not None:
            recorded, recorded_ledger = planting.custodian_events, replay(planting.custodian_events, SNAPSHOT_DAYS)
            refuse_moved_units_or_cash(script.household.household_id, replayed, recorded_ledger)
        notes = None
        path = notes_path(folder / script.source)
        if not script.background and path.is_file():
            try:
                notes = load_notes(path, folder)
            except NotesError as error:
                raise BuildError(str(error)) from error
            problems = check_notes(notes, script.household, simulation.events, planting.entries)
            if problems:
                raise BuildError("; ".join(problems))
        files.update(emit_household(script, recorded, recorded_ledger, market, master, real_tickers, notes))
        # The tax facts are what happened, not what the custodian recorded.
        try:
            facts = tax_unit_facts(script, simulation.events, replayed, market, by_id(master))
        except TaxFactsError as error:
            raise BuildError(f"{script.household.household_id}: {error}") from error
        units += facts
        log = {
            "household_id": script.household.household_id,
            "opening_date": OPENING_DATE.isoformat(),
            "scenario_date": SCENARIO_DATE.isoformat(),
            "events": [event_to_dict(e) for e in simulation.events],
            # Income outside the accounts: the wage and Social Security lines the W-2s and SSA-1099s state.
            "income": [
                {"person_id": i.person_id, "kind": i.kind, "payer": i.payer, "amount": fmt(i.amount), "year": i.year}
                for i in script.household.income
            ],
            # Each tax unit's 2025 facts, gathered from the events: what the tax calculators read.
            "tax_units": [facts_to_dict(f) for f in facts],
        }
        files[event_log_path(script.household.household_id)] = json_text(log).encode()
    files.update(_tax_files(units))
    files[REGISTRY] = json_text({"entries": [e.to_dict() for e in sorted(entries, key=lambda e: e.item_id)]}).encode()
    files[SEALED_HOUSEHOLDS] = json_text({"households": [_sealed_household(s) for s in scripts]}).encode()
    files[METADATA] = json_text(
        {
            "title": "The Indus Casebook: book",
            "notice": NOTICE,
            "licence": DATA_LICENCE,
            "version": BOOK_VERSION,
            "seed": seed,
            "opening_date": OPENING_DATE.isoformat(),
            "scenario_date": SCENARIO_DATE.isoformat(),
            "prices": SYNTHETIC,
            "securities": REAL_TICKERS if real_tickers else ALIASES,
        }
    ).encode()
    if real_tickers:
        files = name_real_tickers(files, master)
    files[MANIFEST] = json_text(
        {
            "version": BOOK_VERSION,
            "seed": seed,
            "households": [
                {"household_id": s.household.household_id, "archetype": s.household.archetype, "state": "emitted"}
                for s in scripts
            ],
            "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
        }
    ).encode()
    return files


def _tax_files(units: list[TaxUnitFacts]) -> dict[str, bytes]:
    """Each household's tax summary from the engine, with every figure the comparison checked. A book
    whose calculators disagree is refused."""
    report: TaxReport = tax_report(units)
    if not report.agrees:
        raise BuildError("the tax calculators disagree:\n" + "\n".join(c.render() for c in report.disagreements))
    files: dict[str, bytes] = {}
    for household in dict.fromkeys(unit.household_id for unit in units):
        summary = {
            "household_id": household,
            "tax_year": TAX_YEAR,
            "summaries": [summary_to_dict(s) for s in report.summaries if s.household_id == household],
            "comparisons": [
                {
                    "tax_unit_id": c.tax_unit_id,
                    "field": c.field,
                    "against": c.against,
                    "engine": None if c.engine is None else fmt(c.engine),
                    "other": None if c.other is None else fmt(c.other),
                    "agrees": c.agrees,
                }
                for c in report.comparisons
                if c.household_id == household
            ],
        }
        files[tax_summary_path(household)] = json_text(summary).encode()
    return files


def _held(snapshot: Snapshot) -> tuple[object, ...]:
    accounts = sorted(snapshot.settled_cash)
    return tuple((a, snapshot.holdings(a), snapshot.settled_cash[a], snapshot.unsettled_cash.get(a)) for a in accounts)


def refuse_moved_units_or_cash(household_id: str, actual: ReplayResult, recorded: ReplayResult) -> None:
    """A planted item may change what the custodian says about a holding, never the holding."""
    pairs = [(actual.opening, recorded.opening)] + [
        (actual.snapshots[d], recorded.snapshots[d]) for d in actual.snapshots
    ]
    for real, kept in pairs:
        if _held(real) != _held(kept):
            raise BuildError(
                f"{household_id}: the custodian's record of events moves units or cash by {real.day}, "
                "which a planted item may not do"
            )


def refuse_real_identifiers(files: dict[str, bytes]) -> None:
    scan = default_scan()
    leaks = [(name, hit.identifier) for name, data in sorted(files.items()) for hit in scan.find(text_of(name, data))]
    if leaks:
        shown = "; ".join(f"{name}: {identifier}" for name, identifier in leaks[:10])
        raise BuildError(f"a default build may not contain a real ticker or security name ({shown})")


def refuse_valid_looking_identifiers(files: dict[str, bytes]) -> None:
    problems = [p for name, data in sorted(files.items()) for p in file_problems(name, data, text_of(name, data))]
    if problems:
        shown = "; ".join(problems[:10])
        raise BuildError(f"identifiers must use ranges that cannot be valid ({shown})")


def refuse_unregistered_differences(out: Path, households: tuple[str, ...]) -> None:
    """docs/SPEC.md, Rules: no two sources disagree without a registry entry."""
    problems = [f"{h}: {p}" for h in households for p in check_sources_agree(out / household_dir(h))]
    if problems:
        shown = "; ".join(problems[:10])
        raise BuildError(f"two sources disagree with no registry entry ({shown})")


def build_book(
    seed: int,
    out: Path,
    scripts_dir: Path,
    real_tickers: bool = False,
    ledger: Path = ID_LEDGER,
    held_out: bool = False,
    background: bool = False,
    extra_scripts: Path | None = None,
    background_archetypes: frozenset[int] | None = None,
) -> BuildResult:
    """Build the book. Real-ticker mode is for runs only: its output goes to out/real/, never published.
    A held-out build (the featured pairs kept back until the freeze) is written outside the repo only."""
    resolved = out.resolve()
    if held_out and (resolved == REPO or REPO in resolved.parents):
        raise BuildError(f"a held-out build is written outside the public repo, not to {out}")
    files = generate_book(
        seed, scripts_dir, real_tickers, ledger, held_out, background, extra_scripts, background_archetypes
    )
    if not real_tickers:
        refuse_real_identifiers(files)
    refuse_valid_looking_identifiers(files)
    if out.exists():
        shutil.rmtree(out)
    for name, data in files.items():
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    households = tuple(
        sorted(
            name.split("/")[1] for name in files if name.startswith("households/") and name.endswith("/crm/crm.json")
        )
    )
    try:
        refuse_unregistered_differences(out, households)
    except BaseException:
        # A refused or broken build leaves no book behind to be mistaken for a good one.
        shutil.rmtree(out)
        raise
    return BuildResult(out, households, len(files))
