"""The static site, rendered from a built, checked book: a page per household, a page per task run, an index."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from casebook.model.dates import SCENARIO_DATE
from casebook.model.files import (
    ACCOUNTS_COLUMNS,
    ACCOUNTS_CSV,
    CRM_JSON,
    DOCUMENTS_INDEX,
    FEE,
    METADATA,
    PORTFOLIO_BILLING,
    PORTFOLIO_HOUSEHOLD,
    PORTFOLIO_IPS,
    POSITIONS_COLUMNS,
    POSITIONS_CSV,
    REGISTRY,
    SEALED_HOUSEHOLDS,
    SOURCE_SETS,
    TRANSACTIONS_COLUMNS,
    TRANSACTIONS_CSV,
    event_log_path,
    household_dir,
    read_cash,
    read_csv,
    read_json,
    read_manifest,
)
from casebook.model.money import parse_decimal, usd
from casebook.model.registry import RegistryEntry, parse_entry
from casebook.notice import NOTICE, NOTICE_HEADLINE
from casebook.site.tasks import task_views

STATIC_DIR = Path(__file__).parent / "static"


def data_root(version: str) -> str:
    """Where the published book files sit inside the site."""
    return f"data/{version}"


@dataclass(frozen=True)
class HouseholdView:
    household_id: str
    name: str
    archetype: int
    archetype_name: str
    pair: int
    role: str
    twin_kind: str | None
    explanation: str | None
    files: dict[str, list[str]]
    accounts: list[dict[str, str]]
    positions: list[dict[str, str]]
    cash: list[dict[str, str]]
    transactions: list[dict[str, str]]
    portfolio: dict[str, Any]
    billing: dict[str, Any]
    ips: dict[str, Any]
    crm: dict[str, Any]
    documents: list[dict[str, Any]]
    events: list[dict[str, Any]]
    planted: RegistryEntry | None

    @property
    def fees(self) -> list[dict[str, str]]:
        return [t for t in self.transactions if t["type"] == FEE]

    @property
    def fee_events(self) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == "fee"]

    @property
    def names(self) -> dict[str, str]:
        return {m["person_id"]: m["name"] for m in self.portfolio["household_membership"]}


def _money(text: str) -> str:
    return usd(parse_decimal(text)) if text else ""


def _household_files(book: Path, household_id: str) -> dict[str, list[str]]:
    root = book / household_dir(household_id)
    return {
        source: sorted(p.relative_to(root).as_posix() for p in (root / source).rglob("*") if p.is_file())
        for source in SOURCE_SETS
    }


def load_household(
    book: Path, household_id: str, sealed: dict[str, Any], entries: list[RegistryEntry]
) -> HouseholdView:
    root = book / household_dir(household_id)
    positions = [
        r for r in read_csv(root, POSITIONS_CSV, POSITIONS_COLUMNS) if r["valuation_date"] == SCENARIO_DATE.isoformat()
    ]
    cash = [
        {"account_id": c.account_id, "settled_cash": usd(c.settled_cash), "unsettled_cash": usd(c.unsettled_cash)}
        for c in read_cash(root)
        if c.valuation_date == SCENARIO_DATE
    ]
    planted = [e for e in entries if e.household_id == household_id]
    return HouseholdView(
        household_id=household_id,
        name=read_json(root, PORTFOLIO_HOUSEHOLD)["name"],
        archetype=int(sealed["archetype"]),
        archetype_name=str(sealed["archetype_name"]),
        pair=int(sealed["pair"]),
        role=str(sealed["role"]),
        twin_kind=sealed["twin_kind"],
        explanation=sealed["explanation"],
        files=_household_files(book, household_id),
        accounts=read_csv(root, ACCOUNTS_CSV, ACCOUNTS_COLUMNS),
        positions=positions,
        cash=cash,
        transactions=read_csv(root, TRANSACTIONS_CSV, TRANSACTIONS_COLUMNS),
        portfolio=read_json(root, PORTFOLIO_HOUSEHOLD),
        billing=read_json(root, PORTFOLIO_BILLING),
        ips=read_json(root, PORTFOLIO_IPS),
        crm=read_json(root, CRM_JSON),
        documents=read_json(root, DOCUMENTS_INDEX)["documents"],
        events=read_json(book, event_log_path(household_id))["events"],
        planted=planted[0] if planted else None,
    )


def environment() -> Environment:
    env = Environment(
        loader=PackageLoader("casebook.site", "templates"),
        autoescape=select_autoescape(["html"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["money"] = _money
    return env


def render_site(
    book: Path, runs: Path | None = None, tasks: Path | None = None, keys: Path | None = None
) -> dict[str, str]:
    manifest = read_manifest(book)
    metadata = read_json(book, METADATA)
    sealed = {h["household_id"]: h for h in read_json(book, SEALED_HOUSEHOLDS)["households"]}
    entries = [parse_entry(e) for e in read_json(book, REGISTRY)["entries"]]
    households = [load_household(book, h.household_id, sealed[h.household_id], entries) for h in manifest.households]
    env = environment()
    common = {
        "notice_headline": NOTICE_HEADLINE,
        "notice_body": NOTICE.removeprefix(NOTICE_HEADLINE).strip(),
        "metadata": metadata,
        "data": data_root(manifest.version),
        "scenario_date": SCENARIO_DATE.isoformat(),
    }
    views = task_views(tasks, runs, keys) if runs and tasks else []
    pages = {
        "index.html": env.get_template("index.html").render(households=households, tasks=views, root=".", **common)
    }
    for view in views:
        pages[f"tasks/{view.task.task_id}.html"] = env.get_template("task.html").render(view=view, root="..", **common)
    for household in households:
        page = env.get_template("household.html").render(
            household=household,
            root="..",
            household_data=f"../{common['data']}/{household_dir(household.household_id)}",
            **common,
        )
        pages[f"households/{household.household_id}.html"] = page
    return pages
