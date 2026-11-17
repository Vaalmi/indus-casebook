"""The hand audit's worksheet: 15 households drawn across the ten archetypes, and every arithmetic
statement their files make that a person can check with a calculator, one numbered line each.

A line gives the figures it rests on and the result the files state, each with the file and row (or
document and page) it comes from; it never gives a result of its own, so the owner works each one by
hand. Tax figures are left to the review (docs/SPEC.md, Review).
"""

import io
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from pathlib import Path
from random import Random

from pypdf import PdfReader

from casebook.checks.book import book_price_rows
from casebook.model.archetypes import ARCHETYPES, HELD_OUT_ARCHETYPES, PRIVATE_PAIRS, frozen
from casebook.model.dates import PRIOR_YEAR_END, SCENARIO_DATE, parse_date
from casebook.model.files import (
    BUY,
    CASH_CSV,
    CRM_JSON,
    DIVIDEND,
    DOCUMENTS_INDEX,
    FEE,
    PORTFOLIO_BILLING,
    PORTFOLIO_HOUSEHOLD,
    PORTFOLIO_POSITIONS,
    POSITIONS_CSV,
    PRICES_CSV,
    REALIZED_CSV,
    SEALED_HOUSEHOLDS,
    SELL,
    STATEMENT_TOTAL,
    TAX_LOTS_CSV,
    TRANSACTIONS_CSV,
    UNIT_SIGNS,
    csv_text,
    household_dir,
    read_cash,
    read_json,
    read_manifest,
    read_positions,
    read_realized,
    read_tax_lots,
    read_transactions,
)
from casebook.model.money import fmt

AUDITED = 15
WORKSHEET = "worksheet.csv"
# The worksheet's columns, which are the audit log's: the owner fills the last four.
COLUMNS = (
    "household_id",
    "archetype",
    "line",
    "kind",
    "statement",
    "figures",
    "stated_result",
    "checked",
    "result",
    "note",
    "fixed_in",
)
# What the worksheet states and the log must keep unchanged.
STATED_COLUMNS = ("household_id", "archetype", "kind", "statement", "figures", "stated_result")

POSITION_VALUE = "position value"
TRADE_VALUE = "trade value"
DIVIDEND_AMOUNT = "dividend"
UNITS_ROLL = "units roll-forward"
CASH_ROLL = "cash roll-forward"
REALIZED_LOT = "realized lot"
QUARTERLY_FEE = "quarterly fee"
STATEMENT_HOLDING = "statement holding value"
STATEMENT_TOTALS = "statement total"
KINDS = (
    POSITION_VALUE,
    TRADE_VALUE,
    DIVIDEND_AMOUNT,
    UNITS_ROLL,
    CASH_ROLL,
    REALIZED_LOT,
    QUARTERLY_FEE,
    STATEMENT_HOLDING,
    STATEMENT_TOTALS,
)

FEATURED = "featured"
ADVISORY = "advisory"
ROUNDING = "rounded half-up to the cent"
_FEE_QUARTER = re.compile(r"quarter to (\d{4}-\d{2}-\d{2})")
_PER_UNIT = re.compile(r", (\d+(?:\.\d+)?) per unit$")
_STATED_TOTAL = re.compile(re.escape(STATEMENT_TOTAL) + r" (\d{4}-\d{2}-\d{2}): (\$[\d,]+\.\d{2})")
_HOLDINGS_HEADER = ("Security", "Units", "Price (synthetic)", "Market value")


class AuditDrawError(ValueError):
    """The book is not one the hand audit may draw from."""


@dataclass(frozen=True)
class Figure:
    name: str
    value: str
    source: str

    def render(self) -> str:
        return f"{self.name} {self.value} [{self.source}]"


@dataclass(frozen=True)
class AuditLine:
    kind: str
    statement: str
    figures: tuple[Figure, ...]
    stated: tuple[Figure, ...]


def draw_households(book: Path, rng: Random) -> tuple[str, ...]:
    """One household per archetype, then five more from the rest, each drawn once; refuses a book that is
    not the public build (a private pair, or a held-out household before the freeze)."""
    sealed = {str(h["household_id"]): h for h in read_json(book, SEALED_HOUSEHOLDS)["households"]}
    by_archetype: dict[int, list[str]] = defaultdict(list)
    for household in read_manifest(book).households:
        entry = sealed[household.household_id]
        archetype, pair = int(entry["archetype"]), int(entry["pair"])
        if entry["set"] != FEATURED and (archetype, pair) in PRIVATE_PAIRS:
            raise AuditDrawError(f"{household.household_id} is a private pair: draw from the public build")
        if entry["set"] == FEATURED and archetype in HELD_OUT_ARCHETYPES and not frozen():
            raise AuditDrawError(f"{household.household_id} is held out until the freeze: draw from the public build")
        by_archetype[archetype].append(household.household_id)
    missing = sorted(set(ARCHETYPES) - set(by_archetype))
    if missing:
        raise AuditDrawError(f"the book has no household of archetype {', '.join(map(str, missing))}")
    drawn = [rng.choice(sorted(by_archetype[archetype])) for archetype in sorted(ARCHETYPES)]
    rest = sorted(h for ids in by_archetype.values() for h in ids if h not in drawn)
    return (*drawn, *rng.sample(rest, AUDITED - len(drawn)))


def write_audit_sheet(book: Path, out: Path, rng: Random) -> list[Path]:
    """The worksheet for the drawn households: one CSV in the log's format and one Markdown file per
    household, under `out/<book version>/`. Returns the files written."""
    drawn = sorted(draw_households(book, rng))
    archetypes = {str(h["household_id"]): int(h["archetype"]) for h in read_json(book, SEALED_HOUSEHOLDS)["households"]}
    folder = out / read_manifest(book).version
    folder.mkdir(parents=True, exist_ok=True)
    for stale in [*folder.glob("HH-*.md"), folder / WORKSHEET]:
        stale.unlink(missing_ok=True)
    rows: list[dict[str, str]] = []
    written: list[Path] = []
    for household_id in drawn:
        lines = household_lines(book / household_dir(household_id))
        archetype = archetypes[household_id]
        rows += [
            {
                "household_id": household_id,
                "archetype": str(archetype),
                "line": str(number),
                "kind": line.kind,
                "statement": line.statement,
                "figures": "; ".join(f.render() for f in line.figures),
                "stated_result": "; ".join(f.render() for f in line.stated),
                "checked": "",
                "result": "",
                "note": "",
                "fixed_in": "",
            }
            for number, line in enumerate(lines, start=1)
        ]
        page = folder / f"{household_id}.md"
        page.write_text(_markdown(household_id, archetype, read_manifest(book).version, lines), encoding="utf-8")
        written.append(page)
    sheet = folder / WORKSHEET
    sheet.write_text(csv_text(COLUMNS, rows), encoding="utf-8")
    return [sheet, *written]


def household_lines(root: Path) -> list[AuditLine]:
    """Every line of one household, in the order: values, trades, dividends, units, cash, realized lots,
    fees, statements."""
    return [
        *_position_values(root),
        *_trades_and_dividends(root),
        *_units(root),
        *_cash(root),
        *_realized(root),
        *_fees(root),
        *_statements(root),
    ]


def _price_sources(root: Path) -> dict[tuple[str, date], int]:
    return {(security, day): line for security, day, _, line in book_price_rows(root)}


def _price_source(prices: dict[tuple[str, date], int], security: str, day: date, where: str) -> str:
    line = prices.get((security, day))
    return where if line is None else f"{where}; {PRICES_CSV} line {line}"


def _position_values(root: Path) -> list[AuditLine]:
    prices = _price_sources(root)
    lines: list[AuditLine] = []
    for row in read_positions(root):
        where = f"{POSITIONS_CSV} line {row.line}"
        lines.append(
            AuditLine(
                POSITION_VALUE,
                f"{row.account_id} {row.security_id} on {row.valuation_date}: value = units x price, {ROUNDING}",
                (
                    Figure("units", str(row.units), where),
                    Figure("price", str(row.price), _price_source(prices, row.security_id, row.valuation_date, where)),
                ),
                (Figure("market value", str(row.market_value), where),),
            )
        )
    for index, item in enumerate(read_json(root, PORTFOLIO_POSITIONS)["positions"]):
        where = f"{PORTFOLIO_POSITIONS} positions[{index}]"
        day = parse_date(str(item["valuation_date"]))
        lines.append(
            AuditLine(
                POSITION_VALUE,
                f"{item['account_id']} {item['security_id']} on {day} (portfolio system): value = units x price, "
                f"{ROUNDING}",
                (
                    Figure("units", str(item["units"]), where),
                    Figure("price", str(item["price"]), _price_source(prices, str(item["security_id"]), day, where)),
                ),
                (Figure("market value", str(item["market_value"]), where),),
            )
        )
    return lines


def _trades_and_dividends(root: Path) -> list[AuditLine]:
    lines: list[AuditLine] = []
    for t in read_transactions(root):
        where = f"{TRANSACTIONS_CSV} line {t.line}"
        if t.type in (BUY, SELL) and t.units is not None and t.price is not None:
            sign = "negative for a buy" if t.type == BUY else "positive for a sale"
            lines.append(
                AuditLine(
                    TRADE_VALUE,
                    f"{t.type} {t.transaction_id}, {t.account_id} {t.security_id} on {t.trade_date}: "
                    f"amount = units x price, {ROUNDING}, {sign}",
                    (Figure("units", str(t.units), where), Figure("price", str(t.price), where)),
                    (Figure("amount", str(t.amount), where),),
                )
            )
        found = _PER_UNIT.search(t.description)
        if t.type == DIVIDEND and t.units is not None and found:
            lines.append(
                AuditLine(
                    DIVIDEND_AMOUNT,
                    f"{t.transaction_id}, {t.account_id} {t.security_id} on {t.trade_date}: "
                    f"amount = units x the dividend per unit, {ROUNDING}",
                    (
                        Figure("units", str(t.units), where),
                        Figure("per unit", found.group(1), f"{where}, description"),
                    ),
                    (Figure("amount", str(t.amount), where),),
                )
            )
    return lines


def _units(root: Path) -> list[AuditLine]:
    opening: dict[tuple[str, str], list[Figure]] = defaultdict(list)
    for lot in read_tax_lots(root):
        if lot.valuation_date == PRIOR_YEAR_END:
            source = f"{TAX_LOTS_CSV} line {lot.line}"
            opening[(lot.account_id, lot.security_id)].append(
                Figure(f"opening lot {lot.lot_id}", str(lot.units), source)
            )
    moves: dict[tuple[str, str], list[Figure]] = defaultdict(list)
    for t in read_transactions(root):
        if t.type in UNIT_SIGNS and t.units is not None and t.security_id:
            signed = t.units * UNIT_SIGNS[t.type]
            moves[(t.account_id, t.security_id)].append(
                Figure(
                    f"{t.type} {t.transaction_id} on {t.trade_date}", fmt(signed), f"{TRANSACTIONS_CSV} line {t.line}"
                )
            )
    closing = {(r.account_id, r.security_id): r for r in read_positions(root) if r.valuation_date == SCENARIO_DATE}
    lines: list[AuditLine] = []
    for key in sorted(set(opening) | set(moves) | set(closing)):
        row = closing.get(key)
        stated = (
            Figure(f"units on {SCENARIO_DATE}", str(row.units), f"{POSITIONS_CSV} line {row.line}")
            if row
            else Figure(f"units on {SCENARIO_DATE}", "0", f"{POSITIONS_CSV}, no row")
        )
        lines.append(
            AuditLine(
                UNITS_ROLL,
                f"{key[0]} {key[1]} from {PRIOR_YEAR_END} to {SCENARIO_DATE}: the opening lots plus acquisitions, "
                "less disposals, splits applied, give the closing units",
                (*opening.get(key, []), *moves.get(key, [])),
                (stated,),
            )
        )
    return lines


def _cash(root: Path) -> list[AuditLine]:
    balances = {(c.account_id, c.valuation_date): c for c in read_cash(root)}
    days = sorted({day for _, day in balances})
    transactions = read_transactions(root)
    lines: list[AuditLine] = []
    for account in sorted({account for account, _ in balances}):
        for start, end in pairwise(days):
            before, after = balances.get((account, start)), balances.get((account, end))
            if before is None or after is None:
                continue
            flows = [
                Figure(
                    f"{t.type} {t.transaction_id} settled {t.settle_date}",
                    str(t.amount),
                    f"{TRANSACTIONS_CSV} line {t.line}",
                )
                for t in transactions
                if t.account_id == account and start < t.settle_date <= end
            ]
            lines.append(
                AuditLine(
                    CASH_ROLL,
                    f"{account} settled cash from {start} to {end}: the opening balance plus the signed flows "
                    "settled after it, up to and on the closing date, give the closing balance",
                    (
                        Figure(f"settled cash on {start}", str(before.settled_cash), f"{CASH_CSV} line {before.line}"),
                        *flows,
                    ),
                    (Figure(f"settled cash on {end}", str(after.settled_cash), f"{CASH_CSV} line {after.line}"),),
                )
            )
    return lines


def _realized(root: Path) -> list[AuditLine]:
    lines: list[AuditLine] = []
    for r in read_realized(root):
        where = f"{REALIZED_CSV} line {r.line}"
        lines.append(
            AuditLine(
                REALIZED_LOT,
                f"lot {r.lot_id} of {r.security_id} in {r.account_id}, sold by {r.transaction_id}: "
                "gain or loss = proceeds less basis; held from the acquired date to the sold date",
                (
                    Figure("units", str(r.units), where),
                    Figure("proceeds", str(r.proceeds), where),
                    Figure("cost basis", str(r.cost_basis), where),
                    Figure("acquired", r.acquired_date.isoformat(), where),
                    Figure("sold", r.sold_date.isoformat(), where),
                ),
                (Figure("gain or loss", str(r.gain), where),),
            )
        )
    return lines


def _fees(root: Path) -> list[AuditLine]:
    """Each quarter's fee per billing group as the portfolio system bills it: the schedule's annual rate on each
    tier of the group's quarter-end value (positions plus cash), the sum divided by four."""
    billing = read_json(root, PORTFOLIO_BILLING)["fee_schedules"]
    schedules = {str(s["schedule_id"]): (i, s) for i, s in enumerate(billing)}
    agreements = [a for a in read_json(root, CRM_JSON)["agreements"] if a["kind"] == ADVISORY]
    positions = read_positions(root)
    cash = read_cash(root)
    debits: dict[date, list[tuple[str, Figure]]] = defaultdict(list)
    for t in read_transactions(root):
        found = _FEE_QUARTER.search(t.description)
        if t.type == FEE and found:
            figure = Figure(
                f"fee debited from {t.account_id} by {t.transaction_id}",
                fmt(-t.amount),
                f"{TRANSACTIONS_CSV} line {t.line}",
            )
            debits[parse_date(found.group(1))].append((t.account_id, figure))
    lines: list[AuditLine] = []
    for quarter_end in sorted(debits):
        for group in read_json(root, PORTFOLIO_HOUSEHOLD)["billing_groups"]:
            accounts = sorted(str(a) for a in group["account_ids"])
            index, schedule = schedules[str(group["schedule_id"])]
            covering = sorted(
                str(a["agreement_id"]) for a in agreements if set(map(str, a["account_ids"])) & set(accounts)
            )
            values = [
                Figure(
                    f"{p.account_id} {p.security_id} value on {quarter_end}",
                    str(p.market_value),
                    f"{POSITIONS_CSV} line {p.line}",
                )
                for p in positions
                if p.account_id in accounts and p.valuation_date == quarter_end
            ]
            for c in cash:
                if c.account_id in accounts and c.valuation_date == quarter_end:
                    where = f"{CASH_CSV} line {c.line}"
                    values += [
                        Figure(f"{c.account_id} settled cash on {quarter_end}", str(c.settled_cash), where),
                        Figure(f"{c.account_id} unsettled cash on {quarter_end}", str(c.unsettled_cash), where),
                    ]
            tiers = [
                Figure(
                    f"tier up to {'any value' if tier['up_to'] is None else tier['up_to']}, annual rate",
                    str(tier["annual_rate"]),
                    f"{PORTFOLIO_BILLING} fee_schedules[{index}].tiers[{n}]",
                )
                for n, tier in enumerate(schedule["tiers"])
            ]
            lines.append(
                AuditLine(
                    QUARTERLY_FEE,
                    f"billing group {group['billing_group_id']} ({', '.join(accounts)}), quarter to {quarter_end}, "
                    f"under {', '.join(covering) or 'no advisory agreement'} on schedule {schedule['schedule_id']}: "
                    "each tier's annual rate on the part of the group's value (positions plus cash) inside it, "
                    f"summed, divided by 4, {ROUNDING}, equals the fees debited from the group's accounts",
                    (*values, *tiers),
                    tuple(f for account, f in debits[quarter_end] if account in accounts),
                )
            )
    return lines


@dataclass(frozen=True)
class _Cell:
    text: str
    page: int


def _statements(root: Path) -> list[AuditLine]:
    lines: list[AuditLine] = []
    for document in read_json(root, DOCUMENTS_INDEX)["documents"]:
        if document["kind"] != "quarterly_statement":
            continue
        name = f"documents/{document['file']}"
        reader = PdfReader(io.BytesIO((root / name).read_bytes()))
        cells = [
            _Cell(text.strip(), number)
            for number, page in enumerate(reader.pages, start=1)
            for text in (page.extract_text() or "").splitlines()
        ]
        lines += _statement_lines(name, str(document["account_id"]), cells)
    return lines


def _statement_lines(name: str, account: str, cells: list[_Cell]) -> list[AuditLine]:
    """A statement's holdings table read back cell by cell (its header repeats on each page it spans), the cash
    and Total rows after it, and the total value the statement states above it."""
    stated_total = next((c for c in cells if _STATED_TOTAL.search(c.text)), None)
    start = next((i for i, c in enumerate(cells) if c.text.startswith("Holdings on")), None)
    if stated_total is None or start is None:
        return []
    found = _STATED_TOTAL.search(stated_total.text)
    assert found is not None
    day = found.group(1)
    table: list[_Cell] = []
    i = start + 1
    while i < len(cells) and cells[i].text != "Cash":
        if cells[i].text not in _HOLDINGS_HEADER:
            table.append(cells[i])
        i += 1
    cash, total = cells[i + 1], cells[i + 3]
    lines: list[AuditLine] = []
    values: list[Figure] = []
    for security, units, price, value in (table[j : j + 4] for j in range(0, len(table) - len(table) % 4, 4)):
        where = f"{name} page {value.page}, holdings row {security.text}"
        lines.append(
            AuditLine(
                STATEMENT_HOLDING,
                f"{account} {security.text} on {day} (quarterly statement): value = units x price, {ROUNDING}",
                (Figure("units", units.text, where), Figure("price", price.text, where)),
                (Figure("market value", value.text, where),),
            )
        )
        values.append(Figure(f"{security.text} market value", value.text, where))
    lines.append(
        AuditLine(
            STATEMENT_TOTALS,
            f"{account} quarterly statement total on {day}: the holdings' market values plus cash",
            (*values, Figure("cash", cash.text, f"{name} page {cash.page}, Cash row")),
            (
                Figure(f"{STATEMENT_TOTAL} {day}", found.group(2), f"{name} page {stated_total.page}"),
                Figure("Total", total.text, f"{name} page {total.page}, Total row"),
            ),
        )
    )
    return lines


def _markdown(household_id: str, archetype: int, version: str, lines: list[AuditLine]) -> str:
    out = [
        f"# Hand audit worksheet: {household_id}",
        "",
        f"Book {version}. Archetype {archetype}, {ARCHETYPES[archetype]}. {len(lines)} lines.",
        "",
        f"Files are under `{household_dir(household_id)}/` in the book, and the prices in `{PRICES_CSV}`. Work each "
        "line from its figures by hand and compare the stated result. Record it in the audit log, the same lines in "
        f"`{WORKSHEET}`: `checked` yes, `result` ok or defect, a `note` for each defect, and `fixed_in` the book "
        "version that fixes it.",
        "",
    ]
    for number, line in enumerate(lines, start=1):
        out += [
            f"## {number}. {line.kind}",
            "",
            line.statement,
            "",
            "| Figure | Value | Source |",
            "| --- | --- | --- |",
        ]
        out += [f"| {f.name} | {f.value} | {f.source} |" for f in line.figures]
        out += [f"| **Stated:** {f.name} | {f.value} | {f.source} |" for f in line.stated]
        out.append("")
    return "\n".join(out)


__all__ = [
    "COLUMNS",
    "KINDS",
    "STATED_COLUMNS",
    "AuditDrawError",
    "AuditLine",
    "Figure",
    "draw_households",
    "household_lines",
    "write_audit_sheet",
]
