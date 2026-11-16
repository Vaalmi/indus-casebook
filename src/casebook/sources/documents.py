"""Document PDFs: a quarterly statement per account, the 2025 tax documents, and the index that dates each document."""

from datetime import date
from decimal import Decimal
from typing import Any

from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Flowable, Paragraph, Spacer, Table, TableStyle

from casebook.model.dates import add_weekdays
from casebook.model.files import DOCUMENTS_INDEX, STATEMENT_TOTAL, SYNTHETIC, json_text
from casebook.model.money import cents, fmt, usd
from casebook.sources import pdf, tax_documents
from casebook.sources.context import EmitContext
from casebook.sources.transactions import transaction_rows

STATEMENT_START = date(2026, 1, 1)
STATEMENT_END = date(2026, 3, 31)
MAILED_AFTER_WEEKDAYS = 5


def _table(rows: list[list[str]]) -> Table:
    table = Table(rows, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
                ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ]
        )
    )
    return table


def _statement(context: EmitContext, account_id: str) -> bytes:
    hh = context.script.household
    account = hh.account(account_id)
    snapshot = context.replayed.snapshots[STATEMENT_END]
    styles = getSampleStyleSheet()
    holdings = [["Security", "Units", "Price (synthetic)", "Market value"]]
    total = Decimal(0)
    for sid, units in snapshot.holdings(account_id).items():
        price = context.market.price(sid, STATEMENT_END)
        value = cents(units * price)
        total += value
        holdings.append([context.label(sid), fmt(units), fmt(price), usd(value)])
    cash = snapshot.settled_cash[account_id] + snapshot.unsettled_cash[account_id]
    holdings.append(["Cash", "", "", usd(cash)])
    holdings.append(["Total", "", "", usd(total + cash)])
    activity = [["Date", "Type", "Description", "Amount"]]
    for row in transaction_rows(context):
        if row.account_id == account_id and STATEMENT_START <= row.trade_date <= STATEMENT_END:
            kind = row.kind.replace("_", " ").capitalize()
            activity.append([row.trade_date.isoformat(), kind, row.description, usd(row.amount)])
    story: list[Flowable] = [
        Paragraph("Quarterly account statement", styles["Title"]),
        Paragraph(f"Account {account_id}: {account.registration}", styles["Normal"]),
        Paragraph("Owners: " + "; ".join(hh.person(p).name for p in hh.owners(account_id)), styles["Normal"]),
        Paragraph(f"Period {STATEMENT_START.isoformat()} to {STATEMENT_END.isoformat()}", styles["Normal"]),
        Paragraph(f"Prices are {SYNTHETIC}.", styles["Normal"]),
        Paragraph(f"{STATEMENT_TOTAL} {STATEMENT_END.isoformat()}: {usd(total + cash)}", styles["Normal"]),
        Spacer(1, 12),
        Paragraph(f"Holdings on {STATEMENT_END.isoformat()}", styles["Heading2"]),
        _table(holdings),
        Spacer(1, 12),
        Paragraph("Activity in the period", styles["Heading2"]),
        _table(activity),
    ]
    return pdf.render(f"Quarterly statement {account_id}", story)


def statement_name(account_id: str) -> str:
    return f"statement-{account_id}-2026Q1.pdf"


def emit(context: EmitContext) -> dict[str, bytes]:
    known = add_weekdays(STATEMENT_END, MAILED_AFTER_WEEKDAYS)
    files: dict[str, bytes] = {}
    index: list[dict[str, Any]] = []
    for account in context.script.household.accounts:
        name = statement_name(account.account_id)
        files[f"documents/{name}"] = _statement(context, account.account_id)
        index.append(
            {
                "document_id": f"D-{account.account_id}-2026Q1",
                "file": name,
                "kind": "quarterly_statement",
                "account_id": account.account_id,
                "period_start": STATEMENT_START.isoformat(),
                "valuation_date": STATEMENT_END.isoformat(),
                "known_as_of": known.isoformat(),
            }
        )
    files.update(tax_documents.emit(context))
    index += tax_documents.index_entries(context)
    files[DOCUMENTS_INDEX] = json_text({"documents": index}).encode()
    return files
