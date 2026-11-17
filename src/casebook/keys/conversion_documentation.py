"""The answer key for whether a year's Roth conversion is documented well enough to report its taxable amount.

The conversion is the custodian's: what left the owner's traditional IRAs as CONVERSION_OUT in the year, and
the year's Form 1099-R for that IRA must report the same gross. Custodians do not track IRA basis, so its
box 2a is no answer; the basis is the prior year's Form 8606, which is documented when the CRM records it
received (a `document_received` record saying so). Then line 2 is the portfolio system's basis for the owner,
carried from that return, and `keys.tax_lines.form_8606` works the pro-rata rule over the owner's traditional
IRAs at the year end. With no Form 8606 on file, the records still settle it when nothing claims basis: the
portfolio system carries none and the CRM records none, so the whole conversion is taxable. But basis with no
Form 8606 behind it, whether the portfolio system carries it or the CRM records the owner's nondeductible
contributions, leaves the taxable amount unresolved, since it can be neither assumed nor ruled out.

A contribution to the owner's traditional IRAs in the year is outside this key: the files would have to say
whether it was deductible.
"""

import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pypdf import PdfReader

from casebook.keys.figures import KeyFigure
from casebook.keys.issues import Issue
from casebook.keys.tax_lines import Form8606Lines, form_8606
from casebook.model.files import (
    ACCOUNTS_COLUMNS,
    ACCOUNTS_CSV,
    CONTRIBUTION,
    CONVERSION_OUT,
    CRM_JSON,
    DISTRIBUTION,
    DOCUMENTS_INDEX,
    PORTFOLIO_HOUSEHOLD,
    PORTFOLIO_TAX_PROFILE,
    QCD,
    read_cash,
    read_csv,
    read_json,
    read_positions,
    read_transactions,
)
from casebook.model.money import fmt, parse_decimal
from casebook.model.tax import IraFlows

type ConversionFinding = Literal["documented", "unresolved"]
DOCUMENTED: ConversionFinding = "documented"
UNRESOLVED: ConversionFinding = "unresolved"
TRADITIONAL_IRA = "traditional_ira"
DOCUMENT_RECEIVED = "document_received"
FORM_1099_R = "form_1099_r"
ZERO = Decimal(0)
# The CRM's record of a Form 8606 received ("2024 Form 1040 and Form 8606 received"), and of a client's
# statement that nondeductible contributions went into an IRA.
_FORM_8606_RECEIVED = re.compile(r"\bForm 8606 received\b")
_BASIS_CLAIM = re.compile(r"\bnondeductible contributions?\b")
_BOX_1 = re.compile(r"Box 1 Gross distribution: \$([\d,]+\.\d{2})")
_BOX_2A = re.compile(r"Box 2a Taxable amount: \$([\d,]+\.\d{2})")


class UnsettledConversionError(ValueError):
    """The household's files hold no conversion this key can review."""


@dataclass(frozen=True)
class ConversionKey:
    household_id: str
    year: int
    person_id: str
    account_ids: tuple[str, ...]
    transaction_ids: tuple[str, ...]
    # The IRA's Form 1099-R for the year, by its file's name, which its document ID also holds.
    form_1099_r: str
    reported_taxable: Decimal  # its box 2a
    converted: Decimal
    finding: ConversionFinding
    # The Form 8606 on file (its CRM record), or None; and the CRM's record of a basis claim, or None.
    form_8606_record: str | None
    claim_record: str | None
    return_record: str | None  # the CRM's record of the prior return received
    basis_prior: Decimal | None
    lines: Form8606Lines | None
    computed_figures: tuple[KeyFigure, ...]

    @property
    def taxable(self) -> Decimal | None:
        return None if self.lines is None else self.lines.line_18

    @property
    def nontaxable(self) -> Decimal | None:
        return None if self.lines is None else self.lines.line_17

    @property
    def issues(self) -> tuple[Issue, ...]:
        if self.finding == UNRESOLVED:
            records = tuple(r for r in (self.return_record, self.claim_record) if r is not None)
            return (Issue("basis claimed with no Form 8606 on file", records),)
        if self.taxable != self.reported_taxable and self.form_8606_record is not None:
            return (
                Issue("Form 1099-R taxable amount is not the Form 8606's", (self.form_1099_r, self.form_8606_record)),
            )
        return ()

    def to_dict(self) -> dict[str, Any]:
        def shown(value: Decimal | None) -> str | None:
            return None if value is None else fmt(value)

        return {
            "household_id": self.household_id,
            "year": self.year,
            "person_id": self.person_id,
            "account_ids": list(self.account_ids),
            "transaction_ids": list(self.transaction_ids),
            "form_1099_r": self.form_1099_r,
            "reported_taxable": fmt(self.reported_taxable),
            "converted": fmt(self.converted),
            "finding": self.finding,
            "form_8606_record": self.form_8606_record,
            "claim_record": self.claim_record,
            "return_record": self.return_record,
            "basis_prior": shown(self.basis_prior),
            "taxable": shown(self.taxable),
            "nontaxable": shown(self.nontaxable),
            "form_8606": None
            if self.lines is None
            else {
                name: shown(getattr(self.lines, name))
                for name in (
                    "line_2",
                    "line_6",
                    "line_7",
                    "line_8",
                    "line_9",
                    "line_10",
                    "line_11",
                    "line_14",
                    "line_18",
                )
            },
            "issues": [{"issue": i.name, "records": list(i.records)} for i in self.issues],
            "computed_figures": [{"label": f.label, "value": fmt(f.value)} for f in self.computed_figures],
        }


def _owner_iras(root: Path) -> dict[str, list[str]]:
    """Each owner's traditional IRAs."""
    household = read_json(root, PORTFOLIO_HOUSEHOLD)
    kinds = {a["account_id"]: a["account_type"] for a in read_csv(root, ACCOUNTS_CSV, ACCOUNTS_COLUMNS)}
    iras: dict[str, list[str]] = {}
    for owned in household["legal_ownership"]:
        account = str(owned["account_id"])
        if kinds.get(account) == TRADITIONAL_IRA:
            for owner in owned["owner_ids"]:
                iras.setdefault(str(owner), []).append(account)
    return iras


def _value_on(root: Path, accounts: list[str], day: date) -> Decimal:
    positions = sum(
        (p.market_value for p in read_positions(root) if p.account_id in accounts and p.valuation_date == day), ZERO
    )
    cash_rows = [c for c in read_cash(root) if c.account_id in accounts and c.valuation_date == day]
    if {c.account_id for c in cash_rows} != set(accounts):
        raise UnsettledConversionError(f"no cash on {day} for every one of {', '.join(accounts)}")
    return positions + sum((c.settled_cash + c.unsettled_cash for c in cash_rows), ZERO)


def _pdf_text(path: Path) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(path.read_bytes())).pages)


def _form_1099_r(root: Path, account: str, year: int) -> tuple[str, Decimal, Decimal]:
    """The IRA's Form 1099-R for the year: its file's name, box 1 and box 2a."""
    documents = [
        d
        for d in read_json(root, DOCUMENTS_INDEX)["documents"]
        if d["kind"] == FORM_1099_R and d["account_id"] == account and str(d["valuation_date"]).startswith(str(year))
    ]
    if len(documents) != 1:
        raise UnsettledConversionError(f"{len(documents)} Forms 1099-R for {account} in {year}")
    text = _pdf_text(root / "documents" / str(documents[0]["file"]))
    gross, taxable = _BOX_1.search(text), _BOX_2A.search(text)
    if gross is None or taxable is None:
        raise UnsettledConversionError(f"{documents[0]['file']} states no box 1 or box 2a")
    return (
        Path(str(documents[0]["file"])).stem,
        parse_decimal(gross.group(1).replace(",", "")),
        parse_decimal(taxable.group(1).replace(",", "")),
    )


def conversion_key(household_root: Path, year: int) -> ConversionKey:
    household_id = str(read_json(household_root, PORTFOLIO_HOUSEHOLD)["household_id"])
    iras = _owner_iras(household_root)
    in_year = [t for t in read_transactions(household_root) if t.trade_date.year == year]
    conversions = [t for t in in_year if t.type == CONVERSION_OUT]
    owners = sorted({o for t in conversions for o, accounts in iras.items() if t.account_id in accounts})
    if len(owners) != 1:
        raise UnsettledConversionError(
            f"{household_id}: {len(owners)} owners converted from a traditional IRA in {year}"
        )
    person = owners[0]
    accounts = sorted(iras[person])
    if any(t.type == CONTRIBUTION and t.account_id in accounts for t in in_year):
        raise UnsettledConversionError(f"{household_id}: a {year} contribution to {person}'s traditional IRAs")
    converted = -sum((t.amount for t in conversions), ZERO)
    from_accounts = sorted({t.account_id for t in conversions})
    if len(from_accounts) != 1:
        raise UnsettledConversionError(f"{household_id}: conversions from {', '.join(from_accounts)}")
    document_id, gross, reported = _form_1099_r(household_root, from_accounts[0], year)
    if gross != converted:
        raise UnsettledConversionError(
            f"{document_id} reports {fmt(gross)}, the custodian's conversions {fmt(converted)}"
        )

    activities = read_json(household_root, CRM_JSON)["activities"]
    received = [a for a in activities if a["kind"] == DOCUMENT_RECEIVED]
    on_file = next((str(a["activity_id"]) for a in received if _FORM_8606_RECEIVED.search(str(a["summary"]))), None)
    claim = next((str(a["activity_id"]) for a in activities if _BASIS_CLAIM.search(str(a["summary"]))), None)
    prior_return = next((str(a["activity_id"]) for a in received if "Form 1040" in str(a["summary"])), None)
    basis = next(
        (
            parse_decimal(str(b["basis"]))
            for b in read_json(household_root, PORTFOLIO_TAX_PROFILE)["ira_basis"]
            if b["person_id"] == person
        ),
        ZERO,
    )
    unresolved = on_file is None and (claim is not None or basis != ZERO)
    distributions = -sum((t.amount for t in in_year if t.type == DISTRIBUTION and t.account_id in accounts), ZERO)
    qcd = -sum((t.amount for t in in_year if t.type == QCD and t.account_id in accounts), ZERO)
    year_end = _value_on(household_root, accounts, date(year, 12, 31))
    figures = [
        KeyFigure("converted", converted),
        KeyFigure(f"traditional IRAs at {year}-12-31", year_end),
        KeyFigure("taxable if no basis", converted),
    ]
    lines = None
    if not unresolved:
        lines = form_8606(IraFlows(person, basis, ZERO, distributions, converted, qcd, year_end))
        figures += [
            KeyFigure(f"Form 8606 {name.replace('_', ' ')}", value)
            for name in (
                "line_2",
                "line_5",
                "line_6",
                "line_7",
                "line_9",
                "line_10",
                "line_11",
                "line_13",
                "line_14",
                "line_17",
                "line_18",
            )
            if (value := getattr(lines, name)) is not None
        ]
        figures.append(KeyFigure("box 2a less the taxable amount", reported - (lines.line_18 or ZERO)))
    return ConversionKey(
        household_id=household_id,
        year=year,
        person_id=person,
        account_ids=tuple(accounts),
        transaction_ids=tuple(sorted({t.transaction_id for t in conversions})),
        form_1099_r=document_id,
        reported_taxable=reported,
        converted=converted,
        finding=UNRESOLVED if unresolved else DOCUMENTED,
        form_8606_record=on_file,
        claim_record=claim if unresolved else None,
        return_record=prior_return,
        basis_prior=None if unresolved else basis,
        lines=lines,
        computed_figures=tuple(figures),
    )
