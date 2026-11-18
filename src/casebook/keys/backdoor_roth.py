"""The answer key for what a 2025 backdoor Roth conversion costs in tax: how much of it is taxable income.

A backdoor Roth is a 2025 contribution to a traditional IRA converted to a Roth IRA in 2025. The
contribution is nondeductible (line 1 of Form 8606): every traditional IRA contribution in the book is
made by a household whose income is over the deduction limit, and the CRM records it as nondeductible.
The conversion's nontaxable share is the person's basis over the value of all their traditional IRAs
(the pro-rata rule of 26 U.S.C. § 408(d)(2)), worked line by line on Form 8606 by `keys.tax_lines`:
line 6 counts every traditional IRA the person owns on 31 December 2025 (the custodian's positions on
that day plus its cash), and nothing in a 401(k). The taxable amount is line 18.

The key reads the account register, the portfolio system's owners and IRA basis, and the custodian's
positions, cash and transactions. It answers in taxable income, not tax dollars: the dollar cost turns
on the whole return, which the firm does not prepare.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from casebook.keys.figures import KeyFigure, w2_wages
from casebook.keys.tax_lines import Form8606Lines, form_8606
from casebook.model.files import (
    ACCOUNTS_COLUMNS,
    ACCOUNTS_CSV,
    CONTRIBUTION,
    CONVERSION_OUT,
    DISTRIBUTION,
    PORTFOLIO_HOUSEHOLD,
    PORTFOLIO_TAX_PROFILE,
    QCD,
    WITHDRAWAL,
    read_cash,
    read_csv,
    read_json,
    read_positions,
    read_transactions,
)
from casebook.model.money import fmt, parse_decimal
from casebook.model.tax import IraFlows

type BackdoorFinding = Literal["pro_rata_tax", "no_pro_rata_tax"]
PRO_RATA_TAX: BackdoorFinding = "pro_rata_tax"
NO_PRO_RATA_TAX: BackdoorFinding = "no_pro_rata_tax"
YEAR = 2025
YEAR_START, YEAR_END = date(YEAR, 1, 1), date(YEAR, 12, 31)
TRADITIONAL_IRA = "traditional_ira"
ZERO = Decimal(0)


class UnsettledBackdoorError(ValueError):
    """The household's files, or this key, cannot settle the conversion's taxable amount."""


@dataclass(frozen=True)
class Backdoor:
    """One person's 2025 backdoor Roth: the contribution and conversion transactions, each traditional
    IRA's value on 31 December 2025, and the Form 8606 they give."""

    person_id: str
    contribution_ids: tuple[str, ...]
    conversion_ids: tuple[str, ...]
    year_end_values: tuple[tuple[str, Decimal], ...]  # (account, value), every traditional IRA the person owns
    form: Form8606Lines

    @property
    def taxable(self) -> Decimal:
        return self.form.line_18 or ZERO

    @property
    def pre_tax_iras(self) -> tuple[str, ...]:
        """The traditional IRAs that hold money on 31 December 2025: what makes the conversion taxable."""
        return tuple(a for a, value in self.year_end_values if value != ZERO)

    def figures(self) -> tuple[KeyFigure, ...]:
        f = self.form
        lines = [
            ("Form 8606 line 1, nondeductible contributions", f.line_1),
            ("Form 8606 line 3, total basis", f.line_3),
            ("Form 8606 line 5", f.line_5),
            ("Form 8606 line 6, traditional IRAs on 31 December 2025", f.line_6),
            ("Form 8606 line 7, distributions", f.line_7),
            ("Form 8606 line 8, converted", f.line_8),
            ("Form 8606 line 9", f.line_9),
            ("Form 8606 line 10, nontaxable share", f.line_10),
            ("Form 8606 line 11, nontaxable part of the conversion", f.line_11),
            ("Form 8606 line 13", f.line_13),
            ("Form 8606 line 14, basis carried to 2026", f.line_14),
            ("Form 8606 line 16, amount converted", f.line_16),
            ("Form 8606 line 17, basis in the amount converted", f.line_17),
            ("Form 8606 line 18, taxable amount", f.line_18),
        ]
        values = [KeyFigure(f"{self.person_id} {label}", v) for label, v in lines if v is not None]
        values += [KeyFigure(f"{account} on 31 December 2025", v) for account, v in self.year_end_values]
        return tuple(values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "person_id": self.person_id,
            "contribution_ids": list(self.contribution_ids),
            "conversion_ids": list(self.conversion_ids),
            "year_end_values": {a: fmt(v) for a, v in self.year_end_values},
            "form_8606": {
                name: (str(value) if name == "line_10" else fmt(value))
                for name, value in vars(self.form).items()
                if name.startswith("line_") and value is not None
            },
        }


@dataclass(frozen=True)
class BackdoorRothKey:
    household_id: str
    finding: BackdoorFinding
    backdoor: Backdoor
    computed_figures: tuple[KeyFigure, ...]

    @property
    def taxable_amount(self) -> Decimal:
        return self.backdoor.taxable

    @property
    def basis_carried(self) -> Decimal:
        return self.backdoor.form.line_14

    def to_dict(self) -> dict[str, Any]:
        return {
            "household_id": self.household_id,
            "finding": self.finding,
            "taxable_amount": fmt(self.taxable_amount),
            "basis_carried": fmt(self.basis_carried),
            "backdoor": self.backdoor.to_dict(),
            "computed_figures": [{"label": f.label, "value": str(f.value)} for f in self.computed_figures],
        }


def _year_end_values(root: Path, account_ids: list[str]) -> list[tuple[str, Decimal]]:
    held: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for row in read_positions(root):
        if row.valuation_date == YEAR_END:
            held[row.account_id] += row.market_value
    cash = {r.account_id: r.settled_cash + r.unsettled_cash for r in read_cash(root) if r.valuation_date == YEAR_END}
    values: list[tuple[str, Decimal]] = []
    for account_id in account_ids:
        if account_id not in cash:
            raise UnsettledBackdoorError(f"{account_id} has no cash row on {YEAR_END}, so its value then is unknown")
        values.append((account_id, held[account_id] + cash[account_id]))
    return values


def _basis(root: Path, person_id: str) -> Decimal:
    for row in read_json(root, PORTFOLIO_TAX_PROFILE).get("ira_basis", []):
        if str(row["person_id"]) == person_id:
            return parse_decimal(str(row["basis"]))
    return ZERO


def backdoor_conversions(household_root: Path) -> tuple[Backdoor, ...]:
    """Every person in the household who made a 2025 backdoor Roth, with their Form 8606."""
    root = household_root
    kinds = {r["account_id"]: r["account_type"] for r in read_csv(root, ACCOUNTS_CSV, ACCOUNTS_COLUMNS)}
    owners = {
        str(o["account_id"]): tuple(str(p) for p in o["owner_ids"])
        for o in read_json(root, PORTFOLIO_HOUSEHOLD)["legal_ownership"]
    }
    iras: dict[str, list[str]] = defaultdict(list)
    for account_id, kind in sorted(kinds.items()):
        if kind == TRADITIONAL_IRA:
            if len(owners.get(account_id, ())) != 1:
                raise UnsettledBackdoorError(f"{account_id} is a traditional IRA without one owner")
            iras[owners[account_id][0]].append(account_id)
    in_year = [t for t in read_transactions(root) if YEAR_START <= t.trade_date <= YEAR_END]
    found: list[Backdoor] = []
    for person_id, accounts in sorted(iras.items()):
        mine = [t for t in in_year if t.account_id in accounts]
        contributions = [t for t in mine if t.type == CONTRIBUTION]
        conversions = [t for t in mine if t.type == CONVERSION_OUT]
        if not contributions or not conversions:
            continue
        values = _year_end_values(root, accounts)
        flows = IraFlows(
            person_id=person_id,
            basis_prior=_basis(root, person_id),
            nondeductible_contributions=sum((t.amount for t in contributions), ZERO),
            distributions=sum((-t.amount for t in mine if t.type in (DISTRIBUTION, WITHDRAWAL)), ZERO),
            conversions=sum((-t.amount for t in conversions), ZERO),
            qcd=sum((-t.amount for t in mine if t.type == QCD), ZERO),
            year_end_value=sum((v for _, v in values), ZERO),
        )
        found.append(
            Backdoor(
                person_id=person_id,
                contribution_ids=tuple(t.transaction_id for t in contributions),
                conversion_ids=tuple(dict.fromkeys(t.transaction_id for t in conversions)),
                year_end_values=tuple(values),
                form=form_8606(flows),
            )
        )
    return tuple(found)


def backdoor_roth_key(household_root: Path) -> BackdoorRothKey:
    household_id = str(read_json(household_root, PORTFOLIO_HOUSEHOLD)["household_id"])
    found = backdoor_conversions(household_root)
    if len(found) != 1:
        raise UnsettledBackdoorError(f"{household_id}: {len(found)} people made a {YEAR} backdoor Roth, not one")
    backdoor = found[0]
    return BackdoorRothKey(
        household_id=household_id,
        finding=PRO_RATA_TAX if backdoor.taxable > ZERO else NO_PRO_RATA_TAX,
        backdoor=backdoor,
        computed_figures=(*backdoor.figures(), *_household_wages(household_root)),
    )


def _household_wages(household_root: Path) -> tuple[KeyFigure, ...]:
    """The household's 2025 wages in all, a sum of its Forms W-2 box 1 an answer may honestly state. The owner's
    fabricated-figure rule (option 1, 18 November 2026) has the key list each honest derivation a live run shows;
    T-MTG-01's skill run stated a couple's joint wages."""
    boxes = [form.box_1 for form in w2_wages(household_root, YEAR_END) if form.box_1 is not None]
    return (KeyFigure("the household's 2025 wages, Forms W-2 box 1", sum(boxes, ZERO)),) if len(boxes) > 1 else ()
