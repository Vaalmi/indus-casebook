"""Archetype 9. Cross-account tax-loss harvester: a replacement purchase in another account or an IRA.

The trap sells a fund at a loss in a taxable account and buys it back in an IRA of one of the
sellers within the wash-sale window: the loss on the shares replaced is disallowed (IRC § 1091)
and, the replacement being in an IRA, never added to any basis (Rev. Rul. 2008-5). The near-miss
twin buys it back in the IRA just outside the window.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from casebook.model.events import Buy, Sell, transaction_id
from casebook.model.files import ACCOUNTS_CSV, PORTFOLIO_HOUSEHOLD, REALIZED_CSV, TRANSACTIONS_CSV
from casebook.model.household import Household
from casebook.model.money import cents, fmt, usd
from casebook.model.registry import FigureTable, RegistryEntry
from casebook.plant.common import PlantContext, PlantError, Planting, names
from casebook.replay import ClosedLot
from casebook.rules import load_rules

ITEM_TYPE = "cross_account_wash_sale"
ZERO = Decimal(0)
IRA_TYPES = {"traditional_ira": "traditional IRA", "roth_ira": "Roth IRA"}
SPOUSES = ("primary", "spouse")


def _window() -> timedelta:
    return timedelta(days=int(load_rules().value("wash_sale_days")))


def _related(hh: Household, account_id: str) -> set[str]:
    """The accounts whose purchases count against a sale from this one: its owners', their spouses' and their
    tax units' (IRS Publication 550: a purchase by the seller's spouse is a purchase by the seller)."""
    people = set(hh.owners(account_id))
    married = {p.person_id for p in hh.members if p.relationship in SPOUSES}
    if people & married:
        people |= married
    for unit in hh.tax_units:
        if people & set(unit.person_ids):
            people |= set(unit.person_ids)
    return {o.account_id for o in hh.ownership if people & set(o.owner_ids)}


@dataclass(frozen=True)
class _Harvest:
    """A sale at a loss, the lots it closed, and every purchase of the same security in a related IRA."""

    sale: Sell
    lots: tuple[ClosedLot, ...]
    repurchases: tuple[Buy, ...]

    @property
    def loss(self) -> Decimal:
        return sum((lot.proceeds - lot.cost for lot in self.lots), ZERO)

    @property
    def basis(self) -> Decimal:
        return sum((lot.cost for lot in self.lots), ZERO)

    def gap(self, buy: Buy) -> timedelta:
        return abs(buy.date - self.sale.date)


def _harvests(context: PlantContext) -> list[_Harvest]:
    hh = context.script.household
    iras = {a.account_id for a in hh.accounts if a.account_type in IRA_TYPES}
    buys = [e for e in context.events if isinstance(e, Buy)]
    harvests: list[_Harvest] = []
    for sale in (e for e in context.events if isinstance(e, Sell)):
        lots = tuple(c for c in context.replayed.closed if c.event_id == sale.event_id)
        if sum((lot.proceeds - lot.cost for lot in lots), ZERO) >= 0:
            continue
        related = _related(hh, sale.account_id) & iras
        found = tuple(
            b
            for b in buys
            if b.security_id == sale.security_id and b.account_id in related and b.account_id != sale.account_id
        )
        harvests.append(_Harvest(sale, lots, tuple(sorted(found, key=lambda b: (abs(b.date - sale.date), b.event_id)))))
    return harvests


def plant_trap(context: PlantContext) -> Planting:
    script = context.script
    assert script.planted is not None
    hh, spec = script.household, script.planted
    window = _window()
    washed = [(h, [b for b in h.repurchases if h.gap(b) <= window]) for h in _harvests(context)]
    washed = [(h, buys) for h, buys in washed if buys]
    if len(washed) != 1:
        raise PlantError(
            f"{spec.item_id}: {len(washed)} loss sales have a purchase of the same security in a related IRA within "
            f"{window.days} days, not one"
        )
    harvest, buys = washed[0]
    sale = harvest.sale
    loss = harvest.loss
    # The IRA sells nothing, so every unit it buys in the window replaces one sold, up to the units sold.
    replaced = min(sum((b.units for b in buys), ZERO), sale.units)
    disallowed = cents(-loss * replaced / sale.units)
    allowed = loss + disallowed
    security = context.label(sale.security_id)
    sellers = names(hh, hh.owners(sale.account_id))
    term = "long-term" if all((sale.date - lot.acquired).days > 365 for lot in harvest.lots) else "short-term"
    bought = "; ".join(
        f"on {b.date.isoformat()}, {(b.date - sale.date).days} days after the sale, "
        f"{names(hh, hh.owners(b.account_id))}'s {IRA_TYPES[hh.account(b.account_id).account_type]} "
        f"{b.account_id} bought {fmt(b.units)} units of the same fund"
        for b in buys
    )
    buyers = {p for b in buys for p in hh.owners(b.account_id)}
    joint = buyers <= set(hh.owners(sale.account_id))
    conclusion = (
        f"On {sale.date.isoformat()} {sellers} sold {fmt(sale.units)} units of {security} ({sale.security_id}) from "
        f"{sale.account_id} for {usd(sale.amount)}, against a basis of {usd(harvest.basis)}: a {term} loss of "
        f"{usd(-loss)}. Then {bought}. A purchase of substantially identical securities within "
        f"{window.days} days before or after a sale at a loss makes it a wash sale (IRC § 1091(a)); a purchase in "
        "the seller's own IRA counts, and the loss it disallows is not added to the basis of the IRA's shares or "
        "of anything else (Rev. Rul. 2008-5)"
        + (
            f", and {names(hh, tuple(sorted(buyers)))} is an owner of the account that sold. "
            if joint
            else "; a purchase by the seller's spouse counts too (IRS Publication 550). "
        )
        + f"The loss on the {fmt(replaced)} units replaced is disallowed: {usd(disallowed)} of the {usd(-loss)}, "
        f"in proportion to the units ({fmt(replaced)} of {fmt(sale.units)}; IRC § 1091(b) and Treas. Reg. "
        f"§ 1.1091-1(c)). The allowed loss is {usd(-allowed)}. The disallowed {usd(disallowed)} is lost for good, "
        "because the replacement is in an IRA. The custodian's realized lots show the whole loss, as it reports "
        "no wash sale across accounts; the joint return should report the sale on Form 8949 with code W and the "
        "disallowed loss as the adjustment in column (g)."
    )
    rows: list[tuple[str, ...]] = [
        (
            "Sale",
            transaction_id(sale.event_id),
            sale.date.isoformat(),
            sale.account_id,
            fmt(sale.units),
            usd(sale.amount),
        ),
        ("Basis of the units sold", "", "", sale.account_id, fmt(sale.units), usd(harvest.basis)),
        ("Loss", "", "", "", fmt(sale.units), usd(loss)),
    ]
    rows += [
        (
            "Replacement purchase",
            transaction_id(b.event_id),
            b.date.isoformat(),
            b.account_id,
            fmt(b.units),
            usd(-b.amount),
        )
        for b in buys
    ]
    rows += [
        ("Disallowed loss", "", "", "", fmt(replaced), usd(disallowed)),
        ("Allowed loss", "", "", "", fmt(sale.units - replaced), usd(allowed)),
    ]
    entry = RegistryEntry(
        item_id=spec.item_id,
        household_id=hh.household_id,
        kind="situation",
        item_type=spec.item_type,
        title="Wash sale across accounts: a loss sale replaced in an IRA within the window",
        sources=(REALIZED_CSV, TRANSACTIONS_CSV, ACCOUNTS_CSV, PORTFOLIO_HOUSEHOLD),
        conclusion=conclusion,
        figures=(
            ("Loss on the sale", usd(-loss)),
            ("Units sold", fmt(sale.units)),
            ("Units replaced", fmt(replaced)),
            ("Disallowed loss", usd(disallowed)),
            ("Allowed loss", usd(-allowed)),
        ),
        table=FigureTable(columns=("Step", "Transaction", "Date", "Account", "Units", "Amount"), rows=tuple(rows)),
        # Known once both the loss sale and its replacements are on record, whichever came first.
        known_as_of=max(sale.date, *(b.date for b in buys)),
        references=(
            transaction_id(sale.event_id),
            *(transaction_id(b.event_id) for b in buys),
            sale.account_id,
            *sorted({b.account_id for b in buys}),
            sale.security_id,
        ),
    )
    return Planting(entries=(entry,))


def check_twin(context: PlantContext, kind: str) -> Planting:
    """A near miss harvests the same way and buys the fund back in a related IRA, but outside the window."""
    hh = context.script.household
    if kind != "near_miss":
        raise PlantError(f"{hh.household_id}: archetype 9's twin is a near miss, not {kind}")
    window = _window()
    harvests = [h for h in _harvests(context) if h.repurchases]
    if not harvests:
        raise PlantError(f"{hh.household_id}: a near miss sells at a loss and buys the security back in a related IRA")
    for harvest in harvests:
        nearest = harvest.repurchases[0]
        if harvest.gap(nearest) <= window:
            raise PlantError(
                f"{hh.household_id}: {nearest.account_id} buys {nearest.security_id} on {nearest.date}, "
                f"{harvest.gap(nearest).days} days from the loss sale on {harvest.sale.date}, inside the "
                f"{window.days}-day window: a wash sale, not a near miss"
            )
    return Planting()
