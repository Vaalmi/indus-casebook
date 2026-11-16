"""Fact sheets: for each household, every fact its CRM notes may assert, with the ID a fact names.

The owner writes a featured household's notes from its fact sheet (docs/PLAN.md, New names). Each
line gives what a notes file's fact needs: the `event_id`, `item_id` or `record` it names, and the
date and amount the notes check compares. Fact sheets are read from a built book; they are for the
owner, not published.
"""

from pathlib import Path
from typing import Any

from casebook.model.files import (
    ACCOUNTS_COLUMNS,
    ACCOUNTS_CSV,
    CRM_JSON,
    PORTFOLIO_HOUSEHOLD,
    REGISTRY,
    event_log_path,
    household_dir,
    read_csv,
    read_json,
)

_AMOUNT_FIELDS = ("amount", "units", "price", "withheld", "share")


def _event_line(event: dict[str, Any]) -> str:
    shown = [f"{k} {event[k]}" for k in ("account_id", "to_account_id", "security_id") if event.get(k)]
    shown += [f"{k} {event[k]}" for k in _AMOUNT_FIELDS if event.get(k) not in (None, "", "0", "0.00")]
    shown += [f"{k} {event[k]}" for k in ("charity", "tax_year", "person_id", "period_end") if event.get(k)]
    return f"| `{event['event_id']}` | {event['date']} | {event['type']} | {', '.join(shown)} |"


def fact_sheet(book: Path, household_id: str) -> str:
    root = book / household_dir(household_id)
    log = read_json(book, event_log_path(household_id))
    crm = read_json(root, CRM_JSON)
    household = read_json(root, PORTFOLIO_HOUSEHOLD)
    entries = [e for e in read_json(book, REGISTRY)["entries"] if e["household_id"] == household_id]
    lines = [
        f"# Fact sheet: {household_id}, {household['name']}",
        "",
        "Every fact a note may assert. A fact in the notes file names one record below by its ID "
        "(`event_id`, `item_id` or `record`) and may give its `date` and `amount`; the notes check "
        "compares them, and every amount and date a note writes must be one its facts give.",
        "",
        "## People (`record` = person ID)",
        "",
        "| Record | Name | Relationship | Born | Died |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| `{m['person_id']}` | {m['name']} | {m['relationship']} | {m['born']} | {m.get('died', '')} |"
        for m in household["household_membership"]
    ]
    lines += ["", "## Accounts (`record` = account ID; the date is the day it opened)", ""]
    lines += ["| Record | Type | Registration | Owners | Opened |", "| --- | --- | --- | --- | --- |"]
    lines += [
        f"| `{a['account_id']}` | {a['account_type']} | {a['registration']} | {a['owners']} | {a['opened']} |"
        for a in read_csv(root, ACCOUNTS_CSV, ACCOUNTS_COLUMNS)
    ]
    lines += ["", "## Agreements (`record` = agreement ID; the date is the day it was signed)", ""]
    lines += ["| Record | Kind | Signed | Accounts | Summary |", "| --- | --- | --- | --- | --- |"]
    lines += [
        f"| `{a['agreement_id']}` | {a['kind']} | {a['signed']} | {', '.join(a['account_ids'])} | {a['summary']} |"
        for a in crm["agreements"]
    ]
    if crm.get("activities"):
        lines += ["", "## CRM activities (`record` = activity ID)", ""]
        lines += ["| Record | Date | Kind | Summary |", "| --- | --- | --- | --- |"]
        lines += [f"| `{a['activity_id']}` | {a['date']} | {a['kind']} | {a['summary']} |" for a in crm["activities"]]
    if log.get("income"):
        lines += ["", "## Income (`record` = person:kind:year; the amount is the year's total)", ""]
        lines += ["| Record | Payer | Amount |", "| --- | --- | --- |"]
        lines += [
            f"| `{i['person_id']}:{i['kind']}:{i['year']}` | {i['payer']} | {i['amount']} |" for i in log["income"]
        ]
    lines += ["", "## Events (`event_id`; the amount is any of the figures shown)", ""]
    lines += ["| Event | Date | Type | Figures |", "| --- | --- | --- | --- |"]
    lines += [_event_line(e) for e in log["events"] if e["type"] != "opening"]
    for entry in entries:
        lines += ["", f"## Planted item `{entry['item_id']}` (`item_id`): {entry['title']}", ""]
        lines += [entry["justified_conclusion"], ""]
        lines += [f"Known as of {entry['known_as_of']}: a note citing this item is dated that day or later.", ""]
        lines += ["| Figure | Value |", "| --- | --- |"]
        lines += [f"| {f['label']} | {f['value']} |" for f in entry["figures"]]
        table = entry["table"]
        if table["rows"]:
            lines += ["", "| " + " | ".join(table["columns"]) + " |", "|" + " --- |" * len(table["columns"])]
            lines += ["| " + " | ".join(row) + " |" for row in table["rows"]]
    lines += [
        "",
        "## The notes file",
        "",
        f"Save beside the script as `{household_id}.notes.toml`:",
        "",
        "```toml",
        f'household_id = "{household_id}"',
        'author = "owner"',
        "",
        "[[facts]]",
        'fact_id = "F-01"',
        'record = "AGR-0000-1"          # or event_id = "E-..." or item_id = "PI-..."',
        "date = 2025-01-01              # optional",
        'amount = "0.00"                # optional',
        'says = "what the fact is, in your words"',
        "",
        "[[notes]]",
        f'note_id = "N-{household_id.removeprefix("HH-")}-01"',
        "date = 2025-01-01",
        'facts = ["F-01"]',
        'text = """',
        "The note as the advisor wrote it.",
        '"""',
        "```",
        "",
    ]
    return "\n".join(lines)


def write_fact_sheets(book: Path, out: Path) -> list[Path]:
    households = read_json(book, "sealed/households.json")["households"]
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for h in households:
        if h["set"] != "featured":
            continue
        path = out / f"{h['household_id']}.md"
        path.write_text(fact_sheet(book, h["household_id"]), encoding="utf-8")
        written.append(path)
    return written
