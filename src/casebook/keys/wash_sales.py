"""The answer key for a wash-sale review: how much of a household's 2025 losses a replacement purchase disallows.

It reads only the household's emitted files: the custodian's accounts, realized lots and transactions,
and the portfolio system's ownership, members and tax units. A 2025 sale at a loss in a taxable account
is a wash sale to the extent that shares of the same security were bought, or vested, within 30 days
before or after it in an account of the seller, the seller's spouse or anyone filing with them
(26 U.S.C. § 1091(a); IRS Publication 550 for the spouse). Each replacement share is matched once,
earliest acquisition first, to the loss lots in the order they were sold (Treas. Reg. § 1.1091-1(b),
(c)); shares bought and then sold in the same sale replace nothing. The loss disallowed on a lot is
its loss in proportion to the units replaced. A replacement in an IRA leaves the disallowed loss lost
for good (Rev. Rul. 2008-5); one in a taxable account would carry it into the replacement's basis
(§ 1091(d)), which this key does not need.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from casebook.keys.figures import KeyFigure
from casebook.model.dates import OPENING_DATE
from casebook.model.files import (
    ACCOUNTS_COLUMNS,
    ACCOUNTS_CSV,
    BUY,
    PORTFOLIO_HOUSEHOLD,
    RSU_VEST,
    RealizedRow,
    TransactionRow,
    read_csv,
    read_json,
    read_realized,
    read_transactions,
)
from casebook.model.money import cents, fmt, per_unit
from casebook.model.tax import TAX_YEAR
from casebook.rules import load_rules

type WashFinding = Literal["wash_sale", "no_wash_sale"]

TAXABLE_TYPES = ("joint_taxable", "individual_taxable")
# An RSU release acquires shares as surely as a purchase does; the tax engine counts it the same way.
ACQUISITIONS = (BUY, RSU_VEST)
SPOUSES = ("primary", "spouse")
ZERO = Decimal(0)


class UnsettledWashSaleError(ValueError):
    """The household's files cannot settle whether a loss was washed."""


def window_days() -> int:
    return int(load_rules(TAX_YEAR).value("wash_sale_days"))


@dataclass(frozen=True)
class Replacement:
    """Units of one acquisition matched to one loss lot."""

    transaction_id: str
    account_id: str
    account_type: str
    trade_date: date
    days_from_sale: int  # negative when bought before the sale
    units: Decimal


@dataclass(frozen=True)
class LossLot:
    """One lot sold at a loss in 2025 from a taxable account, as the custodian's realized lots record it."""

    transaction_id: str
    account_id: str
    lot_id: str
    security_id: str
    acquired_date: date
    sold_date: date
    units: Decimal
    cost_basis: Decimal
    proceeds: Decimal
    replacements: tuple[Replacement, ...]
    disallowed: Decimal

    @property
    def loss(self) -> Decimal:
        return self.cost_basis - self.proceeds

    @property
    def units_replaced(self) -> Decimal:
        return sum((r.units for r in self.replacements), ZERO)

    @property
    def allowed(self) -> Decimal:
        return self.loss - self.disallowed

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "account_id": self.account_id,
            "lot_id": self.lot_id,
            "security_id": self.security_id,
            "acquired_date": self.acquired_date.isoformat(),
            "sold_date": self.sold_date.isoformat(),
            "units": fmt(self.units),
            "cost_basis": fmt(self.cost_basis),
            "proceeds": fmt(self.proceeds),
            "loss": fmt(self.loss),
            "units_replaced": fmt(self.units_replaced),
            "disallowed": fmt(self.disallowed),
            "allowed": fmt(self.allowed),
            "replacements": [
                {
                    "transaction_id": r.transaction_id,
                    "account_id": r.account_id,
                    "account_type": r.account_type,
                    "trade_date": r.trade_date.isoformat(),
                    "days_from_sale": r.days_from_sale,
                    "units": fmt(r.units),
                }
                for r in self.replacements
            ],
        }


@dataclass(frozen=True)
class WashSaleKey:
    household_id: str
    finding: WashFinding
    # Each a positive amount: the 2025 losses as the custodian reports them, the part a replacement
    # disallows, and the part allowed (before any annual limit on capital losses).
    loss_reported: Decimal
    disallowed_loss: Decimal
    allowed_loss: Decimal
    loss_lots: tuple[LossLot, ...]
    computed_figures: tuple[KeyFigure, ...]

    @property
    def washed(self) -> tuple[LossLot, ...]:
        return tuple(lot for lot in self.loss_lots if lot.disallowed > 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "household_id": self.household_id,
            "finding": self.finding,
            "loss_reported": fmt(self.loss_reported),
            "disallowed_loss": fmt(self.disallowed_loss),
            "allowed_loss": fmt(self.allowed_loss),
            "loss_lots": [lot.to_dict() for lot in self.loss_lots],
            "computed_figures": [{"label": f.label, "value": fmt(f.value)} for f in self.computed_figures],
        }


@dataclass(frozen=True)
class _Acquisition:
    """A purchase or an RSU release, from the custodian's transactions."""

    transaction_id: str
    account_id: str
    lot_id: str
    security_id: str
    trade_date: date
    units: Decimal

    def days_from(self, sold: date) -> int:
        return (self.trade_date - sold).days


def _acquisitions(rows: list[TransactionRow]) -> list[_Acquisition]:
    """Earliest first; sorted() is stable, so a day's acquisitions keep the file's order."""
    found = [
        _Acquisition(t.transaction_id, t.account_id, t.lot_id, t.security_id, t.trade_date, t.units)
        for t in rows
        if t.type in ACQUISITIONS and t.units is not None
    ]
    return sorted(found, key=lambda a: a.trade_date)


@dataclass(frozen=True)
class _Household:
    household_id: str
    account_types: dict[str, str]
    owners: dict[str, frozenset[str]]
    spouses: frozenset[str]
    tax_units: tuple[frozenset[str], ...]

    def related_accounts(self, account_id: str) -> frozenset[str]:
        """The accounts whose acquisitions count against a sale from this one: its owners', their spouses'
        and their tax units'."""
        people = set(self.owners[account_id])
        if people & self.spouses:
            people |= self.spouses
        for unit in self.tax_units:
            if people & unit:
                people |= unit
        return frozenset(a for a, owners in self.owners.items() if owners & people)


def _household(root: Path) -> _Household:
    raw = read_json(root, PORTFOLIO_HOUSEHOLD)
    types = {r["account_id"]: r["account_type"] for r in read_csv(root, ACCOUNTS_CSV, ACCOUNTS_COLUMNS)}
    owners = {str(o["account_id"]): frozenset(str(p) for p in o["owner_ids"]) for o in raw["legal_ownership"]}
    unowned = sorted(set(types) - set(owners))
    if unowned:
        raise UnsettledWashSaleError(f"accounts {unowned} have no owner in {PORTFOLIO_HOUSEHOLD}")
    return _Household(
        household_id=str(raw["household_id"]),
        account_types=types,
        owners=owners,
        spouses=frozenset(str(m["person_id"]) for m in raw["household_membership"] if m["relationship"] in SPOUSES),
        tax_units=tuple(frozenset(str(p) for p in u["person_ids"]) for u in raw["tax_units"]),
    )


def _loss_lots(hh: _Household, realized: list[RealizedRow], acquisitions: list[_Acquisition]) -> list[LossLot]:
    window = window_days()
    sold_in: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    for row in realized:
        sold_in[row.transaction_id][row.lot_id] += row.units
    used: dict[str, Decimal] = defaultdict(lambda: ZERO)
    lots: list[LossLot] = []
    # sorted() is stable, so a sale's lots keep the order the custodian closed them in.
    for row in sorted(realized, key=lambda r: r.sold_date):
        taxable = hh.account_types[row.account_id] in TAXABLE_TYPES
        if not taxable or row.sold_date.year != TAX_YEAR or row.proceeds >= row.cost_basis:
            continue
        if row.sold_date - timedelta(days=window) < OPENING_DATE:
            raise UnsettledWashSaleError(
                f"{row.transaction_id} sold on {row.sold_date}, and the transactions start on {OPENING_DATE}: "
                f"purchases in the {window} days before it are not on file"
            )
        related = hh.related_accounts(row.account_id)
        matched: list[Replacement] = []
        count = ZERO
        for buy in acquisitions:
            days = buy.days_from(row.sold_date)
            if buy.security_id != row.security_id or buy.account_id not in related or abs(days) > window:
                continue
            kept = buy.units - sold_in[row.transaction_id][buy.lot_id]
            take = min(kept - used[buy.transaction_id], row.units - count)
            if take <= 0:
                continue
            used[buy.transaction_id] += take
            count += take
            matched.append(
                Replacement(
                    buy.transaction_id, buy.account_id, hh.account_types[buy.account_id], buy.trade_date, days, take
                )
            )
        loss = row.cost_basis - row.proceeds
        lots.append(
            LossLot(
                transaction_id=row.transaction_id,
                account_id=row.account_id,
                lot_id=row.lot_id,
                security_id=row.security_id,
                acquired_date=row.acquired_date,
                sold_date=row.sold_date,
                units=row.units,
                cost_basis=row.cost_basis,
                proceeds=row.proceeds,
                replacements=tuple(matched),
                disallowed=cents(loss * count / row.units),
            )
        )
    return lots


def _figures(
    hh: _Household, lots: list[LossLot], realized: list[RealizedRow], acquisitions: list[_Acquisition]
) -> list[KeyFigure]:
    """Every figure the review invites an answer to derive from the files."""
    figures: list[KeyFigure] = []
    for lot in lots:
        name = f"{lot.transaction_id} lot {lot.lot_id}"
        figures += [
            KeyFigure(f"{name} loss", lot.loss),
            KeyFigure(f"{name} loss per unit", per_unit(lot.loss / lot.units)),
            KeyFigure(f"{name} basis per unit", per_unit(lot.cost_basis / lot.units)),
            KeyFigure(f"{name} proceeds per unit", per_unit(lot.proceeds / lot.units)),
            KeyFigure(f"{name} units replaced", lot.units_replaced),
            KeyFigure(f"{name} units not replaced", lot.units - lot.units_replaced),
            KeyFigure(f"{name} disallowed loss", lot.disallowed),
            KeyFigure(f"{name} allowed loss", lot.allowed),
        ]
        related = hh.related_accounts(lot.account_id)
        # Every acquisition of the security in a related account, in the window or not: an answer that
        # finds one outside it counts the days too.
        figures += [
            KeyFigure(f"days from {lot.transaction_id} to {buy.transaction_id}", Decimal(buy.days_from(lot.sold_date)))
            for buy in acquisitions
            if buy.security_id == lot.security_id and buy.account_id in related
        ]
    by_sale: dict[str, list[RealizedRow]] = defaultdict(list)
    for row in realized:
        if hh.account_types[row.account_id] in TAXABLE_TYPES and row.sold_date.year == TAX_YEAR:
            by_sale[row.transaction_id].append(row)
    for sale, rows in sorted(by_sale.items()):
        figures += [
            KeyFigure(f"{sale} proceeds", sum((r.proceeds for r in rows), ZERO)),
            KeyFigure(f"{sale} basis", sum((r.cost_basis for r in rows), ZERO)),
            KeyFigure(f"{sale} gain or loss", sum((r.proceeds - r.cost_basis for r in rows), ZERO)),
        ]
    taxable_rows = [r for rows in by_sale.values() for r in rows]
    net = sum((r.proceeds - r.cost_basis for r in taxable_rows), ZERO)
    disallowed = sum((lot.disallowed for lot in lots), ZERO)
    figures += [
        KeyFigure(
            "2025 gains on taxable sales",
            sum((r.proceeds - r.cost_basis for r in taxable_rows if r.proceeds > r.cost_basis), ZERO),
        ),
        KeyFigure("2025 net gain or loss on taxable sales, as reported", net),
        KeyFigure("2025 net gain or loss on taxable sales, wash sales adjusted", net + disallowed),
    ]
    return figures


def wash_sale_key(household_root: Path) -> WashSaleKey:
    hh = _household(household_root)
    realized = read_realized(household_root)
    acquisitions = _acquisitions(read_transactions(household_root))
    lots = _loss_lots(hh, realized, acquisitions)
    loss = sum((lot.loss for lot in lots), ZERO)
    disallowed = sum((lot.disallowed for lot in lots), ZERO)
    figures = _figures(hh, lots, realized, acquisitions)
    figures += [
        KeyFigure("loss reported", loss),
        KeyFigure("disallowed loss", disallowed),
        KeyFigure("allowed loss", loss - disallowed),
    ]
    return WashSaleKey(
        household_id=hh.household_id,
        finding="wash_sale" if disallowed > 0 else "no_wash_sale",
        loss_reported=loss,
        disallowed_loss=disallowed,
        allowed_loss=loss - disallowed,
        loss_lots=tuple(lots),
        computed_figures=tuple(dict.fromkeys(figures)),
    )
