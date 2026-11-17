"""The static site, rendered from a built, checked book: a page per household, a page per task run, an index."""

import csv
import io
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
from casebook.site.results import (
    OUTCOME_NAMES,
    OUTCOMES,
    ROLE_NAMES,
    WORKFLOW_NAMES,
    PrivateRunSet,
    load_private_outcomes,
    results,
)
from casebook.site.tasks import ARM_NAMES, ARM_ORDER, load_records, task_views
from casebook.tasks.task import WORKFLOWS

STATIC_DIR = Path(__file__).parent / "static"
FEATURED = "featured"
# The kinds of event that carry each archetype's item: what the events layer shows first.
KEY_EVENTS: dict[int, tuple[str, ...]] = {
    1: ("contribution", "roth_conversion"),
    2: ("sell",),
    3: ("rsu_vest", "sell"),
    4: ("sell", "roth_conversion"),
    5: ("rmd",),
    6: ("qcd", "rmd"),
    7: ("rmd",),
    8: ("death",),
    9: ("buy", "sell"),
    10: ("fee",),
}
# Where an archetype's item is something that did not happen (archetype 7's trap: no distribution left the
# inherited IRA in 2025), no kind of event carries it; the events layer shows that account's events instead.
KEY_ACCOUNT_TYPES: dict[int, str] = {7: "inherited_ira"}
# Where a twin's observations come from, with no registry entry to name its sources.
TWIN_SOURCES = ("custodian/transactions.csv", "crm/crm.json")
_DATES = ("valuation_date", "known_as_of")

# How the household page names each kind of document in the documents index.
DOCUMENT_KINDS = {
    "quarterly_statement": "Quarterly statement",
    "form_1099_composite": "Composite Form 1099",
    "form_1099_r": "Form 1099-R",
    "form_w2": "Form W-2",
    "form_ssa_1099": "Form SSA-1099",
}


def _document(kind: str) -> str:
    return DOCUMENT_KINDS[kind]


def data_root(version: str) -> str:
    """Where the published book files sit inside the site."""
    return f"data/{version}"


# The forms of a return, in the order the return files them, and how the page names each.
RETURN_FORMS = {
    "f1040": "Form 1040",
    "f1040s1": "Schedule 1",
    "f1040s1a": "Schedule 1-A",
    "f1040s2": "Schedule 2",
    "f1040s3": "Schedule 3",
    "f1040sa": "Schedule A",
    "f1040sb": "Schedule B",
    "f1040sd": "Schedule D",
    "f8949": "Form 8949",
    "f8606": "Form 8606",
    "f8960": "Form 8960",
    "f8959": "Form 8959",
}


@dataclass(frozen=True)
class ReturnForm:
    label: str
    path: str  # the book file, under `sealed/`


def _return_forms(book: Path, household_id: str, names: dict[str, str]) -> list[tuple[str, list[ReturnForm]]]:
    """Each filing unit's forms: `f8949-A-1.pdf` is Form 8949, box A, page 1; `f8606-P-1204-2.pdf` is
    that person's Form 8606."""
    root = book / "sealed" / household_id / "returns"
    units: list[tuple[str, list[ReturnForm]]] = []
    for unit in sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []:
        forms: list[tuple[int, str, ReturnForm]] = []
        for pdf in unit.glob("*.pdf"):
            form, _, rest = pdf.stem.partition("-")
            label = RETURN_FORMS[form]
            if form == "f8949":
                box, _, page = rest.partition("-")
                label += f", box {box}, page {page}"
            elif form == "f8606":
                label += f", {names[rest]}"
            path = pdf.relative_to(book).as_posix()
            forms.append((list(RETURN_FORMS).index(form), pdf.name, ReturnForm(label, path)))
        units.append((unit.name, [f for _, _, f in sorted(forms, key=lambda f: (f[0], f[1]))]))
    return units


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

    observations: list[tuple[str, list[str]]]
    returns: list[tuple[str, list[ReturnForm]]]

    @property
    def key_events(self) -> list[dict[str, Any]]:
        return key_events(self.archetype, self.events, self.accounts)

    @property
    def names(self) -> dict[str, str]:
        return {m["person_id"]: m["name"] for m in self.portfolio["household_membership"]}


def key_events(archetype: int, events: list[dict[str, Any]], accounts: list[dict[str, str]]) -> list[dict[str, Any]]:
    """The events behind an archetype's item: those of the kinds that carry it, and, for an item that is what
    never happened in an account, every event of that account."""
    kind = KEY_ACCOUNT_TYPES.get(archetype)
    held = {a["account_id"] for a in accounts if kind is not None and a["account_type"] == kind}
    return [e for e in events if e["type"] in KEY_EVENTS[archetype] or e.get("account_id") in held]


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
    events = read_json(book, event_log_path(household_id))["events"]
    accounts = read_csv(root, ACCOUNTS_CSV, ACCOUNTS_COLUMNS)
    key = key_events(int(sealed["archetype"]), events, accounts)
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
        accounts=accounts,
        positions=positions,
        cash=cash,
        transactions=read_csv(root, TRANSACTIONS_CSV, TRANSACTIONS_COLUMNS),
        portfolio=read_json(root, PORTFOLIO_HOUSEHOLD),
        billing=read_json(root, PORTFOLIO_BILLING),
        ips=read_json(root, PORTFOLIO_IPS),
        crm=read_json(root, CRM_JSON),
        documents=read_json(root, DOCUMENTS_INDEX)["documents"],
        events=events,
        planted=planted[0] if planted else None,
        observations=_observations(root, planted[0] if planted else None, key),
        returns=_return_forms(
            book,
            household_id,
            {m["person_id"]: m["name"] for m in read_json(root, PORTFOLIO_HOUSEHOLD)["household_membership"]},
        ),
    )


def _record_text(record: dict[str, Any]) -> str:
    """One source record as a line: its values, without the dates every record carries."""
    shown: list[str] = []
    for name, value in record.items():
        if name in _DATES or value in ("", None, []):
            continue
        shown.append(f"{name} {', '.join(map(str, value)) if isinstance(value, list) else value}")
    return "; ".join(shown)


def _mentions(record: dict[str, Any], ids: set[str]) -> bool:
    values = [v for value in record.values() for v in (value if isinstance(value, list) else [value])]
    return any(str(v) in ids for v in values)


def _observations(root: Path, planted: RegistryEntry | None, key: list[dict[str, Any]]) -> list[tuple[str, list[str]]]:
    """What each source records about the item: the records in its source files that name the
    item's records, or, for a twin, the records of its archetype's key events."""
    transactions = {"T" + str(e["event_id"]).removeprefix("E") for e in key}
    ids = set(planted.references) if planted else set()
    ids |= transactions | {str(e["account_id"]) for e in key}
    found: list[tuple[str, list[str]]] = []
    for source in planted.sources if planted else TWIN_SOURCES:
        path = root / source
        if path.suffix == ".csv":
            rows = read_csv(root, source, next(csv.reader(io.StringIO(path.read_text(encoding="utf-8")))))
            if source == TRANSACTIONS_CSV:
                rows = [r for r in rows if r["transaction_id"] in transactions or r["transaction_id"] in ids]
            else:
                rows = [r for r in rows if _mentions(r, ids)]
            records = [_record_text(r) for r in rows]
        elif path.suffix == ".json":
            data = read_json(root, source)
            listed = [item for value in data.values() if isinstance(value, list) for item in value]
            records = [_record_text(item) for item in listed if isinstance(item, dict) and _mentions(item, ids)]
        else:
            continue
        if records:
            found.append((source, records))
    return found


def environment() -> Environment:
    env = Environment(
        loader=PackageLoader("casebook.site", "templates"),
        autoescape=select_autoescape(["html"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["money"] = _money
    env.filters["document"] = _document
    return env


def render_site(
    book: Path,
    runs: Path | None = None,
    tasks: Path | None = None,
    keys: Path | None = None,
    private_outcomes: Path | None = None,
) -> dict[str, str]:
    manifest = read_manifest(book)
    metadata = read_json(book, METADATA)
    sealed = {h["household_id"]: h for h in read_json(book, SEALED_HOUSEHOLDS)["households"]}
    entries = [parse_entry(e) for e in read_json(book, REGISTRY)["entries"]]
    # The site shows the featured households (docs/SPEC.md: "a list of the 20 featured households; one
    # page per household"); the background households are in the book's files.
    households = [
        load_household(book, h.household_id, sealed[h.household_id], entries)
        for h in manifest.households
        if sealed[h.household_id]["set"] == FEATURED
    ]
    env = environment()
    common = {
        "notice_headline": NOTICE_HEADLINE,
        "notice_body": NOTICE.removeprefix(NOTICE_HEADLINE).strip(),
        "metadata": metadata,
        "data": data_root(manifest.version),
        "scenario_date": SCENARIO_DATE.isoformat(),
    }
    views = task_views(tasks, runs, keys) if runs and tasks else []
    private: list[PrivateRunSet] = load_private_outcomes(private_outcomes) if private_outcomes else []
    sections = results(load_records(runs) if runs and runs.is_dir() else {}, tasks, private) if tasks else []
    pages = {
        "index.html": env.get_template("index.html").render(
            households=households, tasks=views, results=bool(sections), root=".", **common
        )
    }
    if sections:
        pages["results.html"] = env.get_template("results.html").render(
            sections=sections,
            arms=ARM_ORDER,
            arm_names=ARM_NAMES,
            workflows=WORKFLOWS,
            workflow_names=WORKFLOW_NAMES,
            outcomes=OUTCOMES,
            outcome_names=OUTCOME_NAMES,
            roles=ROLE_NAMES,
            root=".",
            **common,
        )
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
