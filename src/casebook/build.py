"""`casebook build`: generate, replay, plant and emit every household, then write the manifest."""

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from casebook import BOOK_VERSION
from casebook.generate.script import HouseholdScript, load_scripts
from casebook.generate.simulate import simulate
from casebook.model.archetypes import ARCHETYPES
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
    json_text,
)
from casebook.model.money import fmt
from casebook.model.registry import RegistryEntry
from casebook.notice import NOTICE
from casebook.plant import plant
from casebook.published_text import text_of
from casebook.replay import replay
from casebook.securities.market import Market, build_market
from casebook.securities.master import Security, load_master
from casebook.securities.scan import default_scan
from casebook.sources import emit_household
from casebook.sources.context import SNAPSHOT_DAYS

DATA_LICENCE = "CC-BY-4.0"


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
            "date": day.isoformat(),
            "price": fmt(price),
            "price_label": SYNTHETIC,
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
        "twin_kind": script.twin.kind if script.twin else None,
        "explanation": script.twin.explanation if script.twin else None,
        "script": script.source,
    }


def generate_book(seed: int, scripts_dir: Path, real_tickers: bool = False) -> dict[str, bytes]:
    master = load_master()
    market = build_market(master, seed, BOOK_VERSION)
    scripts = load_scripts(scripts_dir)
    if not scripts:
        raise BuildError(f"no household scripts under {scripts_dir}")
    files = _book_files(master, market, real_tickers)
    entries: list[RegistryEntry] = []
    for script in scripts:
        simulation = simulate(script, market)
        replayed = replay(simulation.events, SNAPSHOT_DAYS)
        entries += plant(script, simulation.quarters)
        files.update(emit_household(script, simulation.events, replayed, market, master, real_tickers))
        log = {
            "household_id": script.household.household_id,
            "opening_date": OPENING_DATE.isoformat(),
            "scenario_date": SCENARIO_DATE.isoformat(),
            "events": [event_to_dict(e) for e in simulation.events],
        }
        files[event_log_path(script.household.household_id)] = json_text(log).encode()
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


def refuse_real_identifiers(files: dict[str, bytes]) -> None:
    scan = default_scan()
    leaks = [(name, hit.identifier) for name, data in sorted(files.items()) for hit in scan.find(text_of(name, data))]
    if leaks:
        shown = "; ".join(f"{name}: {identifier}" for name, identifier in leaks[:10])
        raise BuildError(f"a default build may not contain a real ticker or security name ({shown})")


def build_book(seed: int, out: Path, scripts_dir: Path, real_tickers: bool = False) -> BuildResult:
    """Build the book. Real-ticker mode is for runs only: its output goes to out/real/, never published."""
    files = generate_book(seed, scripts_dir, real_tickers)
    if not real_tickers:
        refuse_real_identifiers(files)
    if out.exists():
        shutil.rmtree(out)
    for name, data in files.items():
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    households = tuple(
        name.split("/")[1] for name in files if name.startswith("households/") and name.endswith("/crm/crm.json")
    )
    return BuildResult(out, tuple(sorted(households)), len(files))
