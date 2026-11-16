"""No two sources disagree without a registry entry.

The facts compared, wherever two sources both state them: holdings (units, price and value) and
cash on the scenario date in the custodian and the portfolio system; the accounts each knows and
their owners; the people in the CRM and the portfolio system, and the beneficiaries the custodian
names among them; CRM householding agreements against the portfolio system's billing groups; and
each statement's total, holdings, cash, owners, registration and activity against the custodian.
"""

import io
import re
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from casebook.checks.book import book_securities, registered
from casebook.model.dates import SCENARIO_DATE
from casebook.model.files import (
    ACCOUNTS_COLUMNS,
    ACCOUNTS_CSV,
    BENEFICIARIES_COLUMNS,
    BENEFICIARIES_CSV,
    CASH_CSV,
    CRM_JSON,
    DOCUMENTS_INDEX,
    PORTFOLIO_HOUSEHOLD,
    PORTFOLIO_POSITIONS,
    POSITIONS_CSV,
    STATEMENT_TOTAL,
    TRANSACTIONS_CSV,
    read_cash,
    read_csv,
    read_json,
    read_positions,
    read_transactions,
)
from casebook.model.money import parse_decimal

ZERO = Decimal(0)
HOUSEHOLDING = "householding"
_TOTAL = re.compile(re.escape(STATEMENT_TOTAL) + r" (\d{4}-\d{2}-\d{2}): \$([\d,]+\.\d{2})")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_DOLLARS = re.compile(r"-?\$[\d,]+\.\d{2}")
_ACCOUNT_LINE = re.compile(r"Account (\S+): (.+)")
_OWNERS_LINE = re.compile(r"Owners: (.*)")


def _value_on(root: Path, day: date) -> dict[str, Decimal]:
    values: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for row in read_positions(root):
        if row.valuation_date == day:
            values[row.account_id] += row.market_value
    for row in read_cash(root):
        if row.valuation_date == day:
            values[row.account_id] += row.settled_cash + row.unsettled_cash
    return values


def check_sources_agree(root: Path) -> list[str]:
    problems: list[str] = []

    def differ(first: str, second: str, what: str, ref: str) -> None:
        if not registered(root, first, second, refs=(ref,)):
            problems.append(f"{first} and {second} disagree with no registry entry: {what}")

    portfolio = read_json(root, PORTFOLIO_POSITIONS)
    held = {
        (r.account_id, r.security_id): (r.units, r.price, r.market_value)
        for r in read_positions(root)
        if r.valuation_date == SCENARIO_DATE
    }
    listed = {
        (str(p["account_id"]), str(p["security_id"])): tuple(
            parse_decimal(str(p[f])) for f in ("units", "price", "market_value")
        )
        for p in portfolio["positions"]
    }
    for key in sorted(set(held) | set(listed)):
        if held.get(key) != listed.get(key):
            shown = [_position(x.get(key)) for x in (held, listed)]
            differ(POSITIONS_CSV, PORTFOLIO_POSITIONS, f"{key[0]} {key[1]} holds {shown[0]} and {shown[1]}", key[0])
    cash = {
        c.account_id: c.settled_cash + c.unsettled_cash for c in read_cash(root) if c.valuation_date == SCENARIO_DATE
    }
    recorded = {str(i["account_id"]): parse_decimal(str(i["cash"])) for i in portfolio["cash"]}
    for account in sorted(set(cash) | set(recorded)):
        if account not in cash or account not in recorded or cash[account] != recorded[account]:
            shown = [str(x[account]) if account in x else "no cash line" for x in (cash, recorded)]
            differ(CASH_CSV, PORTFOLIO_POSITIONS, f"{account} cash {shown[0]} and {shown[1]}", account)

    household = read_json(root, PORTFOLIO_HOUSEHOLD)
    groups = [set(map(str, g["account_ids"])) for g in household["billing_groups"]]
    crm = read_json(root, CRM_JSON)
    for agreement in crm["agreements"]:
        if agreement["kind"] == HOUSEHOLDING:
            joined = set(map(str, agreement["account_ids"]))
            if not any(joined <= group for group in groups):
                what = (
                    f"householding agreement {agreement['agreement_id']} joins {', '.join(sorted(joined))}, "
                    "which the billing groups keep apart"
                )
                differ(CRM_JSON, PORTFOLIO_HOUSEHOLD, what, str(agreement["agreement_id"]))

    names = {str(m["person_id"]): str(m["name"]) for m in household["household_membership"]}
    owners = {
        str(o["account_id"]): {names.get(str(p), str(p)) for p in o["owner_ids"]} for o in household["legal_ownership"]
    }
    accounts = {a["account_id"]: a for a in read_csv(root, ACCOUNTS_CSV, ACCOUNTS_COLUMNS)}
    for account in accounts.values():
        on_file = {n.strip() for n in account["owners"].split(";") if n.strip()}
        if on_file != owners.get(account["account_id"], set()):
            differ(
                ACCOUNTS_CSV,
                PORTFOLIO_HOUSEHOLD,
                f"{account['account_id']} owners {sorted(on_file)}",
                account["account_id"],
            )
    for account_id in sorted(set(owners) - set(accounts)):
        differ(ACCOUNTS_CSV, PORTFOLIO_HOUSEHOLD, f"{account_id} is in the portfolio system only", account_id)

    members = {str(m["person_id"]): (str(m["name"]), str(m["relationship"])) for m in household["household_membership"]}
    contacts = {str(c["person_id"]): (str(c["name"]), str(c["relationship"])) for c in crm["contacts"]}
    for person in sorted(set(members) | set(contacts)):
        if members.get(person) != contacts.get(person):
            shown = [", ".join(x[person]) if person in x else "no record" for x in (contacts, members)]
            differ(CRM_JSON, PORTFOLIO_HOUSEHOLD, f"{person} is {shown[0]} and {shown[1]}", person)
    for row in read_csv(root, BENEFICIARIES_CSV, BENEFICIARIES_COLUMNS):
        person = row["person_id"]
        if person and members.get(person, ("",))[0] != row["name"]:
            known = members[person][0] if person in members else "no household member"
            what = f"{row['account_id']}'s {row['designation']} beneficiary {person} is {row['name']} and {known}"
            differ(BENEFICIARIES_CSV, PORTFOLIO_HOUSEHOLD, what, row["account_id"])

    for document in read_json(root, DOCUMENTS_INDEX)["documents"]:
        if document["kind"] != "quarterly_statement":
            continue
        where = f"documents/{document['file']}"
        text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO((root / where).read_bytes())).pages)
        found = _TOTAL.search(text)
        if found is None:
            problems.append(f"{where}: states no total value")
            continue
        day, total = date.fromisoformat(found.group(1)), parse_decimal(found.group(2).replace(",", ""))
        account = str(document["account_id"])
        header = _ACCOUNT_LINE.search(text)
        named = _OWNERS_LINE.search(text)
        on_file = accounts.get(account)
        if header is None or named is None or on_file is None:
            problems.append(f"{where}: names no account, registration or owners that the custodian holds")
            continue
        if (header.group(1), header.group(2).strip()) != (account, on_file["registration"]):
            differ(where, ACCOUNTS_CSV, f"{account} is registered as {header.group(2).strip()}", account)
        if named.group(1).strip() != on_file["owners"]:
            differ(where, ACCOUNTS_CSV, f"{account} is owned by {named.group(1).strip()}", account)
        start = date.fromisoformat(str(document["period_start"]))
        kept = sorted(
            (t.trade_date, t.type.replace("_", " ").capitalize(), t.description, t.amount)
            for t in read_transactions(root)
            if t.account_id == account and start <= t.trade_date <= day
        )
        shown_activity = sorted(_activity(text))
        if shown_activity != kept:
            # Counted, so a row the statement repeats is a difference too.
            shown_count, kept_count = Counter(shown_activity), Counter(kept)
            extra = sorted(((shown_count - kept_count) + (kept_count - shown_count)).elements())
            what = (
                f"{account} activity from {start} to {day} differs, first at {extra[0][0]} {extra[0][2]} {extra[0][3]}"
            )
            differ(where, TRANSACTIONS_CSV, what, account)
        custodian = _value_on(root, day).get(account, ZERO)
        if custodian != total:
            differ(where, POSITIONS_CSV, f"{account} is worth {total} on {day}, and {custodian}", account)
        statement = _holdings(text, book_securities(root))
        if statement is None:
            problems.append(f"{where}: its holdings table cannot be read")
            continue
        stated, stated_cash = statement
        held = {r.security_id: r for r in read_positions(root) if r.account_id == account and r.valuation_date == day}
        for security in sorted(set(stated) | set(held)):
            row = held.get(security)
            listed = stated.get(security)
            if row is None or listed is None or listed != (row.units, row.price, row.market_value):
                shown = "no holding" if listed is None else f"{listed[0]} units at {listed[1]} worth {listed[2]}"
                kept = "no position" if row is None else f"{row.units} units at {row.price} worth {row.market_value}"
                differ(
                    where,
                    POSITIONS_CSV,
                    f"{account} {security} on {day}: the statement shows {shown}, the custodian {kept}",
                    account,
                )
        cash = {c.account_id: c.settled_cash + c.unsettled_cash for c in read_cash(root) if c.valuation_date == day}
        if stated_cash != cash.get(account):
            differ(
                where,
                CASH_CSV,
                f"{account} cash on {day}: the statement shows {stated_cash}, the custodian {cash.get(account)}",
                account,
            )
    return problems


def _position(position: tuple[Decimal, ...] | None) -> str:
    if position is None:
        return "nothing"
    units, price, value = position
    return f"{units} units at {price} worth {value}"


def _activity(text: str) -> list[tuple[date, str, str, Decimal]]:
    """A statement's activity table, read back: date, type, description, amount, one cell per line."""
    lines = [line.strip() for line in text.splitlines()]
    try:
        start = lines.index("Activity in the period")
    except ValueError:
        return []
    rows: list[tuple[date, str, str, Decimal]] = []
    for i in range(start, len(lines) - 3):
        if _DAY.fullmatch(lines[i]) and _DOLLARS.fullmatch(lines[i + 3]):
            rows.append((date.fromisoformat(lines[i]), lines[i + 1], lines[i + 2], _dollars(lines[i + 3])))
    return rows


def _holdings(
    text: str, securities: dict[str, str]
) -> tuple[dict[str, tuple[Decimal, Decimal, Decimal]], Decimal] | None:
    """A statement's holdings table, read back cell by cell: security, units, price, market value; then its cash."""
    lines = [line.strip() for line in text.splitlines()]
    try:
        start = (
            lines.index("Market value", next(i for i, line in enumerate(lines) if line.startswith("Holdings on"))) + 1
        )
        end = lines.index("Cash", start)
        cash = _dollars(lines[end + 1])
    except (StopIteration, ValueError, IndexError):
        return None
    cells = lines[start:end]
    if len(cells) % 4:
        return None
    rows: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
    for name, units, price, value in (cells[i : i + 4] for i in range(0, len(cells), 4)):
        rows[securities.get(name, name)] = (parse_decimal(units), parse_decimal(price), _dollars(value))
    return rows, cash


def _dollars(text: str) -> Decimal:
    negative = text.startswith("-")
    value = parse_decimal(text.lstrip("-").replace("$", "").replace(",", ""))
    return -value if negative else value
