"""The 2025 tax documents as the custodian, the employers and the Social Security Administration issue them.

A composite Form 1099 (DIV, INT and B) per taxable account with 2025 dividends, interest or sales;
a Form 1099-R per retirement account and distribution code with a 2025 distribution, conversion
or QCD; a Form W-2 per wage line; and an SSA-1099 per Social Security line. The custodian's forms
are drawn from the events and ledger as it recorded them, so a planted error shows on them: an RSU
lot's zero basis on the 1099-B, a QCD coded as an ordinary distribution on the 1099-R.
"""

import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Flowable, Paragraph, Spacer, Table, TableStyle

from casebook.model.events import (
    CharitableDistribution,
    Dividend,
    Event,
    RequiredDistribution,
    RothConversion,
    Withdrawal,
)
from casebook.model.files import SYNTHETIC
from casebook.model.household import Household
from casebook.model.money import fmt, usd
from casebook.model.tax import EXEMPT, QUALIFIED, TAX_YEAR, covered, dividend_character, long_term
from casebook.replay import ClosedLot
from casebook.sources import pdf
from casebook.sources.context import EmitContext

ZERO = Decimal(0)
YEAR_START, YEAR_END = date(TAX_YEAR, 1, 1), date(TAX_YEAR, 12, 31)

# The day each document is issued: its `known_as_of` in the documents index.
COMPOSITE_ISSUED = date(2026, 2, 17)
FORM_1099_R_ISSUED = date(2026, 1, 30)
W2_ISSUED = date(2026, 1, 30)
SSA_1099_ISSUED = date(2026, 1, 31)

COMPOSITE_1099 = "form_1099_composite"
FORM_1099_R = "form_1099_r"
FORM_W2 = "form_w2"
FORM_SSA_1099 = "form_ssa_1099"

TAXABLE = ("joint_taxable", "individual_taxable")
IRA, PLAN, INHERITED = "traditional_ira", "401k", "inherited_ira"
RETIREMENT = (IRA, PLAN, INHERITED)
WAGES, SOCIAL_SECURITY = "wages", "social_security"


# Instructions for Forms 1099-R and 5498 (2025), box 7 and Table 1, Guide to Distribution Codes.
EARLY_NO_EXCEPTION = "1"  # under 59½, no known exception
EARLY_EXCEPTION = "2"  # under 59½ and an exception applies: a Roth IRA conversion
DEATH = "4"  # paid to a decedent's beneficiary, whatever the age
NORMAL = "7"  # 59½ or older, a Roth IRA conversion included
QCD = "Y"  # a QCD, entered first with 4 or 7
EARLY_AGE_YEARS, EARLY_AGE_MONTHS = 59, 6


@dataclass(frozen=True)
class SaleLine:
    """One 1099-B line: one lot a 2025 sale closed, at the custodian's basis."""

    description: str
    acquired: date
    sold: date
    proceeds: Decimal
    basis: Decimal
    long_term: bool
    covered: bool


@dataclass(frozen=True)
class DividendLine:
    security: str
    character: str
    amount: Decimal


@dataclass(frozen=True)
class Composite1099:
    account_id: str
    ordinary_dividends: Decimal  # 1099-DIV box 1a, qualified included
    qualified_dividends: Decimal  # box 1b
    exempt_interest_dividends: Decimal  # box 12
    interest: Decimal  # 1099-INT box 1
    dividends: tuple[DividendLine, ...]
    sales: tuple[SaleLine, ...]


@dataclass(frozen=True)
class Form1099R:
    account_id: str
    person_id: str
    code: str  # box 7
    gross: Decimal  # box 1
    taxable: Decimal  # box 2a
    not_determined: bool  # box 2b, taxable amount not determined
    withheld: Decimal  # box 4
    ira_sep_simple: bool  # the IRA/SEP/SIMPLE checkbox in box 7


@dataclass(frozen=True)
class FormW2:
    person_id: str
    ordinal: int  # the person's nth wage line for the year
    employer: str
    wages: Decimal  # box 1, and box 5 (the book has no pre-tax deferrals)


@dataclass(frozen=True)
class FormSsa1099:
    person_id: str
    ordinal: int
    net_benefits: Decimal  # box 5; box 3 the same, nothing repaid in box 4


type TaxForm = Composite1099 | Form1099R | FormW2 | FormSsa1099


def _in_year(day: date) -> bool:
    return YEAR_START <= day <= YEAR_END


def reached_early_age(born: date, day: date) -> bool:
    """Whether a person has reached 59½ on `day`: six calendar months after the 59th birthday."""
    month = born.month + EARLY_AGE_MONTHS
    year = born.year + EARLY_AGE_YEARS + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return day >= date(year, month, min(born.day, calendar.monthrange(year, month)[1]))


def _composites(context: EmitContext) -> list[Composite1099]:
    hh = context.script.household
    forms: list[Composite1099] = []
    for account in hh.accounts:
        if account.account_type not in TAXABLE:
            continue
        aid = account.account_id
        paid = [e for e in context.events if isinstance(e, Dividend) and e.account_id == aid and _in_year(e.date)]
        closed = [c for c in context.replayed.closed if c.account_id == aid and _in_year(c.sold)]
        if not paid and not closed:
            continue
        by_security: dict[str, Decimal] = {}
        for dividend in paid:
            by_security[dividend.security_id] = by_security.get(dividend.security_id, ZERO) + dividend.amount
        lines = tuple(
            DividendLine(context.label(sid), dividend_character(context.securities[sid].alias), amount)
            for sid, amount in sorted(by_security.items())
        )
        exempt = sum((d.amount for d in lines if d.character == EXEMPT), ZERO)
        qualified = sum((d.amount for d in lines if d.character == QUALIFIED), ZERO)
        total = sum((d.amount for d in lines), ZERO)
        forms.append(
            Composite1099(aid, total - exempt, qualified, exempt, ZERO, lines, tuple(_sale(context, c) for c in closed))
        )
    return forms


def _sale(context: EmitContext, closed: ClosedLot) -> SaleLine:
    return SaleLine(
        description=f"{fmt(closed.units)} {context.label(closed.security_id)}",
        acquired=closed.acquired,
        sold=closed.sold,
        proceeds=closed.proceeds,
        basis=closed.cost,
        long_term=long_term(closed.acquired, closed.sold),
        covered=covered(context.securities[closed.security_id].alias, closed.acquired),
    )


def _distribution(event: Event) -> tuple[Decimal, Decimal] | None:
    """A 1099-R event's gross amount and federal tax withheld, or None for an event no 1099-R reports."""
    match event:
        case RequiredDistribution():
            return -event.amount, event.withheld
        case Withdrawal() | CharitableDistribution():
            return -event.amount, ZERO
        case RothConversion():
            return event.amount, ZERO
        case _:
            return None


def distribution_code(household: Household, event: Event, account_type: str) -> str:
    """Box 7 as the custodian codes the event it recorded."""
    owner = household.person(household.owners(event.account_id)[0])
    adult = reached_early_age(owner.born, event.date)
    if account_type == INHERITED:
        code = DEATH
    elif isinstance(event, RothConversion):
        code = NORMAL if adult else EARLY_EXCEPTION
    else:
        code = NORMAL if adult else EARLY_NO_EXCEPTION
    return QCD + code if isinstance(event, CharitableDistribution) else code


def _forms_1099_r(context: EmitContext) -> list[Form1099R]:
    """One form per account and box 7 code: a distribution whose codes cannot combine needs a
    separate Form 1099-R (Instructions for Forms 1099-R and 5498 (2025), box 7)."""
    hh = context.script.household
    kind = {a.account_id: a.account_type for a in hh.accounts}
    totals: dict[tuple[str, str], tuple[Decimal, Decimal]] = {}
    for event in context.events:
        if not _in_year(event.date) or kind[event.account_id] not in RETIREMENT:
            continue
        amounts = _distribution(event)
        if amounts is None:
            continue
        key = (event.account_id, distribution_code(hh, event, kind[event.account_id]))
        gross, withheld = totals.get(key, (ZERO, ZERO))
        totals[key] = (gross + amounts[0], withheld + amounts[1])
    forms: list[Form1099R] = []
    for (account_id, code), (gross, withheld) in totals.items():
        is_ira = kind[account_id] in (IRA, INHERITED)
        forms.append(Form1099R(account_id, hh.owners(account_id)[0], code, gross, gross, is_ira, withheld, is_ira))
    return forms


def _income_forms(context: EmitContext) -> list[TaxForm]:
    forms: list[TaxForm] = []
    seen: dict[tuple[str, str], int] = {}
    for line in context.script.household.income:
        if line.year != TAX_YEAR or line.kind not in (WAGES, SOCIAL_SECURITY):
            continue
        ordinal = seen[(line.person_id, line.kind)] = seen.get((line.person_id, line.kind), 0) + 1
        if line.kind == WAGES:
            forms.append(FormW2(line.person_id, ordinal, _named(context, line.payer), line.amount))
        else:
            forms.append(FormSsa1099(line.person_id, ordinal, line.amount))
    return forms


def _named(context: EmitContext, text: str) -> str:
    """An employer named after a security is named by its ticker in a real-ticker build, as the
    build renames script text in its CSV and JSON files."""
    if not context.real_tickers:
        return text
    for security in sorted(context.securities.values(), key=lambda s: len(s.alias), reverse=True):
        text = text.replace(security.alias, security.real_ticker)
    return text


def tax_forms(context: EmitContext) -> list[TaxForm]:
    """Every 2025 tax document the household receives, with the figures each states."""
    return [*_composites(context), *_forms_1099_r(context), *_income_forms(context)]


@dataclass(frozen=True)
class Filed:
    """Where a form sits in the documents index."""

    document_id: str
    file: str
    kind: str
    issued: date
    account_id: str | None = None
    person_id: str | None = None


def filed(form: TaxForm) -> Filed:
    match form:
        case Composite1099():
            stem = f"{form.account_id}-1099-{TAX_YEAR}"
            return Filed(f"D-{stem}", f"{stem}.pdf", COMPOSITE_1099, COMPOSITE_ISSUED, account_id=form.account_id)
        case Form1099R():
            stem = f"{form.account_id}-1099R-{form.code}-{TAX_YEAR}"
            return Filed(f"D-{stem}", f"{stem}.pdf", FORM_1099_R, FORM_1099_R_ISSUED, account_id=form.account_id)
        case FormW2():
            stem = f"{form.person_id}-W2-{form.ordinal}-{TAX_YEAR}"
            return Filed(f"D-{stem}", f"{stem}.pdf", FORM_W2, W2_ISSUED, person_id=form.person_id)
        case FormSsa1099():
            stem = f"{form.person_id}-SSA1099-{form.ordinal}-{TAX_YEAR}"
            return Filed(f"D-{stem}", f"{stem}.pdf", FORM_SSA_1099, SSA_1099_ISSUED, person_id=form.person_id)


def index_entry(form: TaxForm) -> dict[str, Any]:
    where = filed(form)
    entry: dict[str, Any] = {"document_id": where.document_id, "file": where.file, "kind": where.kind}
    if where.account_id is not None:
        entry["account_id"] = where.account_id
    if where.person_id is not None:
        entry["person_id"] = where.person_id
    entry["valuation_date"] = YEAR_END.isoformat()
    entry["known_as_of"] = where.issued.isoformat()
    return entry


def index_entries(context: EmitContext) -> list[dict[str, Any]]:
    """The documents index entries for the household's tax documents, in the order `emit` draws them."""
    return [index_entry(form) for form in tax_forms(context)]


def _table(rows: Sequence[Sequence[str]]) -> Table:
    table = Table([list(r) for r in rows], repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7),
                ("FONT", (0, 1), (-1, -1), "Helvetica", 7),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, "black"),
            ]
        )
    )
    return table


def _recipient(household: Household, person_ids: Sequence[str]) -> list[str]:
    first = household.person(person_ids[0])
    return [
        "Recipient: " + "; ".join(household.person(p).name for p in person_ids),
        f"Recipient's TIN: {first.tax_id}",
    ]


def _checked(flag: bool) -> str:
    return "X" if flag else "(blank)"


def _draw_composite(context: EmitContext, form: Composite1099) -> bytes:
    hh = context.script.household
    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    account = hh.account(form.account_id)
    header = [
        f"Payer: the custodian of account {form.account_id}",
        f"Account {form.account_id}: {account.registration}",
        *_recipient(hh, hh.owners(form.account_id)),
        f"Proceeds are at {SYNTHETIC} prices.",
    ]
    story: list[Flowable] = [
        Paragraph(f"{TAX_YEAR} Composite Form 1099: DIV, INT and B", styles["Title"]),
        *(Paragraph(text, normal) for text in header),
        Spacer(1, 10),
        Paragraph(f"Form 1099-DIV, Dividends and Distributions, {TAX_YEAR}", styles["Heading2"]),
        Paragraph(f"Box 1a Total ordinary dividends: {usd(form.ordinary_dividends)}", normal),
        Paragraph(f"Box 1b Qualified dividends: {usd(form.qualified_dividends)}", normal),
        Paragraph(f"Box 2a Total capital gain distributions: {usd(ZERO)}", normal),
        Paragraph(f"Box 4 Federal income tax withheld: {usd(ZERO)}", normal),
        Paragraph(f"Box 12 Exempt-interest dividends: {usd(form.exempt_interest_dividends)}", normal),
        Spacer(1, 6),
    ]
    if form.dividends:
        rows = [["Security", "Treatment", "Amount"]] + [
            [d.security, d.character, usd(d.amount)] for d in form.dividends
        ]
        story += [Paragraph("Dividend detail", styles["Heading3"]), _table(rows)]
    story += [
        Spacer(1, 10),
        Paragraph(f"Form 1099-INT, Interest Income, {TAX_YEAR}", styles["Heading2"]),
        Paragraph(f"Box 1 Interest income: {usd(form.interest)}", normal),
        Spacer(1, 10),
        Paragraph(f"Form 1099-B, Proceeds From Broker Transactions, {TAX_YEAR}", styles["Heading2"]),
    ]
    if form.sales:
        rows = [
            ["Description", "Acquired", "Sold", "Proceeds", "Cost basis", "Gain or loss", "Term", "Covered"],
            *(
                [
                    s.description,
                    s.acquired.isoformat(),
                    s.sold.isoformat(),
                    usd(s.proceeds),
                    usd(s.basis),
                    usd(s.proceeds - s.basis),
                    "Long-term" if s.long_term else "Short-term",
                    "Covered" if s.covered else "Noncovered",
                ]
                for s in form.sales
            ),
        ]
        story.append(_table(rows))
        for term, is_long in (("Short-term", False), ("Long-term", True)):
            part = [s for s in form.sales if s.long_term == is_long]
            proceeds = sum((s.proceeds for s in part), ZERO)
            basis = sum((s.basis for s in part), ZERO)
            story.append(Paragraph(f"{term} total: proceeds {usd(proceeds)}, cost basis {usd(basis)}", normal))
    else:
        story.append(Paragraph(f"No sales in {TAX_YEAR}.", normal))
    return pdf.render(f"Composite Form 1099 {form.account_id} {TAX_YEAR}", story)


def _draw_1099_r(context: EmitContext, form: Form1099R) -> bytes:
    hh = context.script.household
    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    account = hh.account(form.account_id)
    lines = [
        f"Payer: the custodian of account {form.account_id}",
        f"Account {form.account_id}: {account.registration}",
        *_recipient(hh, (form.person_id,)),
        f"Box 1 Gross distribution: {usd(form.gross)}",
        f"Box 2a Taxable amount: {usd(form.taxable)}",
        f"Box 2b Taxable amount not determined: {_checked(form.not_determined)}",
        f"Box 4 Federal income tax withheld: {usd(form.withheld)}",
        f"Box 7 Distribution code(s): {form.code}",
        f"Box 7 IRA/SEP/SIMPLE: {_checked(form.ira_sep_simple)}",
    ]
    story: list[Flowable] = [
        Paragraph(
            f"{TAX_YEAR} Form 1099-R, Distributions From Pensions, Annuities, Retirement or Profit-Sharing Plans, "
            "IRAs, Insurance Contracts, etc.",
            styles["Title"],
        ),
        *(Paragraph(text, normal) for text in lines),
    ]
    return pdf.render(f"Form 1099-R {form.account_id} {TAX_YEAR}", story)


def _draw_w2(context: EmitContext, form: FormW2) -> bytes:
    person = context.script.household.person(form.person_id)
    styles = getSampleStyleSheet()
    lines = [
        f"Employer: {form.employer}",
        f"Employee: {person.name}",
        f"Employee's social security number: {person.tax_id}",
        f"Box 1 Wages, tips, other compensation: {usd(form.wages)}",
        f"Box 5 Medicare wages and tips: {usd(form.wages)}",
    ]
    story: list[Flowable] = [
        Paragraph(f"{TAX_YEAR} Form W-2, Wage and Tax Statement", styles["Title"]),
        *(Paragraph(text, styles["Normal"]) for text in lines),
    ]
    return pdf.render(f"Form W-2 {form.person_id} {TAX_YEAR}", story)


def _draw_ssa_1099(context: EmitContext, form: FormSsa1099) -> bytes:
    person = context.script.household.person(form.person_id)
    styles = getSampleStyleSheet()
    lines = [
        "Issued by the Social Security Administration",
        f"Box 1 Name: {person.name}",
        f"Box 2 Beneficiary's social security number: {person.tax_id}",
        f"Box 3 Benefits paid in {TAX_YEAR}: {usd(form.net_benefits)}",
        f"Box 4 Benefits repaid to SSA in {TAX_YEAR}: {usd(ZERO)}",
        f"Box 5 Net benefits for {TAX_YEAR}: {usd(form.net_benefits)}",
    ]
    story: list[Flowable] = [
        Paragraph(f"{TAX_YEAR} Form SSA-1099, Social Security Benefit Statement", styles["Title"]),
        *(Paragraph(text, styles["Normal"]) for text in lines),
    ]
    return pdf.render(f"Form SSA-1099 {form.person_id} {TAX_YEAR}", story)


def _draw(context: EmitContext, form: TaxForm) -> bytes:
    match form:
        case Composite1099():
            return _draw_composite(context, form)
        case Form1099R():
            return _draw_1099_r(context, form)
        case FormW2():
            return _draw_w2(context, form)
        case FormSsa1099():
            return _draw_ssa_1099(context, form)


def emit(context: EmitContext) -> dict[str, bytes]:
    """The tax documents' PDFs, by path under the household's folder; `index_entries` lists them."""
    return {f"documents/{filed(form).file}": _draw(context, form) for form in tax_forms(context)}
