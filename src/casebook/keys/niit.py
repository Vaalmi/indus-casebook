"""The answer key for a year-end planning call on the net investment income tax, the SALT limit and asset
location, for a household with one tax unit whose only income is wages and its taxable accounts.

Net investment income is the 2025 dividends and the net realized gain in the taxable accounts (the
custodian's transactions and realized lots); what happens inside a retirement account is not income.
Modified AGI is the wages on the 2025 Forms W-2 plus that income: the key refuses a household with any
other income or adjustment it can see (a retirement-account flow in 2025, a Form 1099-R or SSA-1099, a
capital loss carryforward, a net capital loss), since then modified AGI needs the whole return. The tax
of 26 U.S.C. § 1411 is 3.8 percent of the lesser of net investment income and modified AGI over the
filing status's threshold. The SALT deduction limit of § 164(b)(7) is the 2025 cap, reduced by 30 percent
of modified AGI over the phase-down threshold but not below the floor. Asset location: the fixed-income
funds (the IPS's asset classes) the taxable accounts hold on 31 December 2025, and their 2025 dividends,
when the retirement accounts hold none.
"""

import re
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pypdf import PdfReader

from casebook.keys.figures import KeyFigure
from casebook.model.files import (
    ACCOUNTS_COLUMNS,
    ACCOUNTS_CSV,
    BUY,
    DIVIDEND,
    DOCUMENTS_INDEX,
    FEE,
    PORTFOLIO_HOUSEHOLD,
    PORTFOLIO_IPS,
    PORTFOLIO_TAX_PROFILE,
    SELL,
    read_csv,
    read_json,
    read_positions,
    read_realized,
    read_transactions,
)
from casebook.model.money import cents, fmt, parse_decimal
from casebook.rules import Rules, load_rules

type NiitFinding = Literal["niit_owed", "no_niit"]
NIIT_OWED: NiitFinding = "niit_owed"
NO_NIIT: NiitFinding = "no_niit"
YEAR = 2025
YEAR_START, YEAR_END = date(YEAR, 1, 1), date(YEAR, 12, 31)
TAXABLE = ("joint_taxable", "individual_taxable")
RETIREMENT = ("traditional_ira", "roth_ira", "401k", "inherited_ira")
FIXED_INCOME = "Fixed income"
W2, FORM_1099_R, SSA_1099 = "form_w2", "form_1099_r", "form_ssa_1099"
MARRIED_FILING_SEPARATELY = "married_filing_separately"
NIIT_THRESHOLD = {
    "married_filing_jointly": "niit_threshold_mfj",
    "married_filing_separately": "niit_threshold_mfs",
    "single": "niit_threshold_single",
    "head_of_household": "niit_threshold_hoh",
}
# Form W-2 box 1, as the custodian's copy on file prints it.
_BOX_1 = re.compile(r"Box 1 Wages, tips, other compensation: \$([\d,]+\.\d{2})")
ZERO = Decimal(0)


class UnsettledNiitError(ValueError):
    """The household's files, or this key, cannot settle modified AGI and the tax on it."""


@dataclass(frozen=True)
class Sale:
    transaction_id: str
    sold: date
    gain: Decimal


@dataclass(frozen=True)
class NiitKey:
    household_id: str
    tax_unit_id: str
    filing_status: str
    finding: NiitFinding
    wages: tuple[tuple[str, Decimal], ...]  # (person, Form W-2 box 1)
    dividends: Decimal
    sales: tuple[Sale, ...]
    threshold: Decimal
    rate: Decimal
    salt_cap: Decimal
    salt_threshold: Decimal
    salt_limit: Decimal
    # Asset location: the fixed-income funds in the taxable accounts on 31 December 2025, and their 2025 dividends.
    bonds_in_taxable: tuple[str, ...]
    bond_dividends: Decimal
    bonds_sheltered: bool
    computed_figures: tuple[KeyFigure, ...]

    @property
    def total_wages(self) -> Decimal:
        return sum((w for _, w in self.wages), ZERO)

    @property
    def gain(self) -> Decimal:
        return sum((s.gain for s in self.sales), ZERO)

    @property
    def net_investment_income(self) -> Decimal:
        return self.dividends + self.gain

    @property
    def modified_agi(self) -> Decimal:
        return self.total_wages + self.net_investment_income

    @property
    def excess(self) -> Decimal:
        return max(self.modified_agi - self.threshold, ZERO)

    @property
    def taxed(self) -> Decimal:
        return min(self.net_investment_income, self.excess)

    @property
    def niit(self) -> Decimal:
        return cents(self.rate * self.taxed)

    @property
    def asset_location_point(self) -> bool:
        """Bonds sit in a taxable account while the retirement accounts hold none: worth raising."""
        return bool(self.bonds_in_taxable) and not self.bonds_sheltered

    def to_dict(self) -> dict[str, Any]:
        return {
            "household_id": self.household_id,
            "tax_unit_id": self.tax_unit_id,
            "filing_status": self.filing_status,
            "finding": self.finding,
            "wages": {p: fmt(w) for p, w in self.wages},
            "dividends": fmt(self.dividends),
            "sales": [
                {"transaction_id": s.transaction_id, "sold": s.sold.isoformat(), "gain": fmt(s.gain)}
                for s in self.sales
            ],
            "net_investment_income": fmt(self.net_investment_income),
            "modified_agi": fmt(self.modified_agi),
            "threshold": fmt(self.threshold),
            "excess": fmt(self.excess),
            "niit": fmt(self.niit),
            "salt_limit": fmt(self.salt_limit),
            "bonds_in_taxable": list(self.bonds_in_taxable),
            "bond_dividends": fmt(self.bond_dividends),
            "asset_location_point": self.asset_location_point,
            "computed_figures": [{"label": f.label, "value": fmt(f.value)} for f in self.computed_figures],
        }


def _wages(root: Path, person_ids: tuple[str, ...]) -> tuple[tuple[str, Decimal], ...]:
    found: list[tuple[str, Decimal]] = []
    for doc in read_json(root, DOCUMENTS_INDEX)["documents"]:
        if doc["kind"] != W2 or str(doc["valuation_date"]) != YEAR_END.isoformat():
            continue
        if str(doc["person_id"]) not in person_ids:
            raise UnsettledNiitError(f"{doc['file']} is for {doc['person_id']}, who is not in the tax unit")
        text = "\n".join(page.extract_text() or "" for page in PdfReader(root / "documents" / str(doc["file"])).pages)
        box = _BOX_1.search(text)
        if box is None:
            raise UnsettledNiitError(f"{doc['file']} shows no box 1 wages")
        found.append((str(doc["person_id"]), parse_decimal(box.group(1).replace(",", ""))))
    return tuple(found)


def _refuse_other_income(root: Path, kinds: dict[str, str], tax_unit_id: str) -> None:
    for doc in read_json(root, DOCUMENTS_INDEX)["documents"]:
        if doc["kind"] in (FORM_1099_R, SSA_1099) and str(doc["valuation_date"]) == YEAR_END.isoformat():
            raise UnsettledNiitError(f"{doc['file']}: income beyond wages and the taxable accounts")
    for t in read_transactions(root):
        retirement = kinds.get(t.account_id) in RETIREMENT
        if retirement and YEAR_START <= t.trade_date <= YEAR_END and t.type not in (DIVIDEND, BUY, SELL, FEE):
            raise UnsettledNiitError(f"{t.transaction_id}: a {t.type} in a retirement account in {YEAR}")
    for row in read_json(root, PORTFOLIO_TAX_PROFILE).get("loss_carryforwards", []):
        if str(row["tax_unit_id"]) == tax_unit_id and (
            parse_decimal(str(row["short_term"])) or parse_decimal(str(row["long_term"]))
        ):
            raise UnsettledNiitError(f"{tax_unit_id} carries a capital loss into {YEAR}")


def _salt_limit(rules: Rules, filing_status: str, modified_agi: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """The cap, the phase-down threshold and the limit after the phase-down."""
    if filing_status == MARRIED_FILING_SEPARATELY:
        raise UnsettledNiitError("the key does not work the SALT limit for married filing separately")
    cap, threshold = rules.value("salt_cap"), rules.value("salt_phase_down_threshold")
    over = max(modified_agi - threshold, ZERO)
    return cap, threshold, max(cap - cents(rules.value("salt_phase_down_rate") * over), rules.value("salt_floor"))


def niit_key(household_root: Path) -> NiitKey:
    root = household_root
    household = read_json(root, PORTFOLIO_HOUSEHOLD)
    household_id = str(household["household_id"])
    units = household["tax_units"]
    if len(units) != 1:
        raise UnsettledNiitError(f"{household_id} has {len(units)} tax units; the key works one")
    unit = units[0]
    tax_unit_id, filing_status = str(unit["tax_unit_id"]), str(unit["filing_status"])
    person_ids = tuple(str(p) for p in unit["person_ids"])
    if filing_status not in NIIT_THRESHOLD:
        raise UnsettledNiitError(f"{household_id}: no NIIT threshold for filing status {filing_status!r}")
    kinds = {r["account_id"]: r["account_type"] for r in read_csv(root, ACCOUNTS_CSV, ACCOUNTS_COLUMNS)}
    _refuse_other_income(root, kinds, tax_unit_id)
    taxable = {a for a, k in kinds.items() if k in TAXABLE}
    retirement = {a for a, k in kinds.items() if k in RETIREMENT}

    in_year = [t for t in read_transactions(root) if YEAR_START <= t.trade_date <= YEAR_END]
    dividends = [t for t in in_year if t.type == DIVIDEND and t.account_id in taxable]
    by_sale: dict[tuple[str, date], Decimal] = {}
    for lot in read_realized(root):
        if lot.account_id in taxable and lot.sold_date.year == YEAR:
            sale = (lot.transaction_id, lot.sold_date)
            by_sale[sale] = by_sale.get(sale, ZERO) + lot.gain
    sales = tuple(Sale(t, d, g) for (t, d), g in sorted(by_sale.items(), key=lambda item: (item[0][1], item[0][0])))
    if sum((s.gain for s in sales), ZERO) < ZERO:
        raise UnsettledNiitError(f"{household_id}: a net capital loss for {YEAR}; the loss limit needs the return")

    classes = {str(c["security_id"]): str(c["asset_class"]) for c in read_json(root, PORTFOLIO_IPS)["asset_classes"]}
    bonds = {s for s, c in classes.items() if c == FIXED_INCOME}
    year_end = [p for p in read_positions(root) if p.valuation_date == YEAR_END and p.units]
    bonds_in_taxable = tuple(sorted({p.security_id for p in year_end if p.account_id in taxable} & bonds))
    bonds_sheltered = any(p.account_id in retirement and p.security_id in bonds for p in year_end)
    bond_dividends = sum((t.amount for t in dividends if t.security_id in bonds_in_taxable), ZERO)

    rules = load_rules(YEAR)
    wages = _wages(root, person_ids)
    total_dividends = sum((t.amount for t in dividends), ZERO)
    modified_agi = sum((w for _, w in wages), ZERO) + total_dividends + sum((s.gain for s in sales), ZERO)
    salt_cap, salt_threshold, salt_limit = _salt_limit(rules, filing_status, modified_agi)
    key = NiitKey(
        household_id=household_id,
        tax_unit_id=tax_unit_id,
        filing_status=filing_status,
        finding=NO_NIIT,
        wages=wages,
        dividends=total_dividends,
        sales=sales,
        threshold=rules.value(NIIT_THRESHOLD[filing_status]),
        rate=rules.value("niit_rate"),
        salt_cap=salt_cap,
        salt_threshold=salt_threshold,
        salt_limit=salt_limit,
        bonds_in_taxable=bonds_in_taxable,
        bond_dividends=bond_dividends,
        bonds_sheltered=bonds_sheltered,
        computed_figures=(),
    )
    figures = [
        KeyFigure("wages", key.total_wages),
        KeyFigure("dividends in the taxable accounts", key.dividends),
        KeyFigure("net realized gain in the taxable accounts", key.gain),
        *(KeyFigure(f"gain on {s.transaction_id}", s.gain) for s in sales),
        *(KeyFigure(f"modified AGI without {s.transaction_id}", key.modified_agi - s.gain) for s in sales),
        KeyFigure("modified AGI without the realized gains", key.modified_agi - key.gain),
        KeyFigure("net investment income", key.net_investment_income),
        KeyFigure("modified AGI", key.modified_agi),
        KeyFigure("NIIT threshold", key.threshold),
        KeyFigure("modified AGI over the threshold", key.excess),
        KeyFigure("modified AGI under the threshold", max(key.threshold - key.modified_agi, ZERO)),
        KeyFigure("lesser of net investment income and the excess", key.taxed),
        KeyFigure("net investment income tax", key.niit),
        KeyFigure("SALT cap", salt_cap),
        KeyFigure("SALT phase-down threshold", salt_threshold),
        KeyFigure("SALT deduction limit", salt_limit),
        # The floor is also the cap before 2025: an answer may well compare the two.
        KeyFigure("SALT floor", rules.value("salt_floor")),
        KeyFigure("modified AGI under the SALT phase-down threshold", max(salt_threshold - key.modified_agi, ZERO)),
        KeyFigure("bond fund dividends in the taxable accounts", bond_dividends),
    ]
    return replace(key, finding=NIIT_OWED if key.niit > ZERO else NO_NIIT, computed_figures=tuple(figures))
