"""Archetype 2. High-income household near thresholds: net investment income tax, the SALT limit, asset location.

The trap's December sale of a long-held fund pushes modified AGI over the NIIT threshold; the
near-miss twin's stays under it, by less than NEAR_MISS_MARGIN.
"""

from dataclasses import dataclass
from decimal import Decimal

from casebook.model.dates import parse_date
from casebook.model.events import (
    CharitableDistribution,
    Contribution,
    Dividend,
    RequiredDistribution,
    RothConversion,
    Sell,
    Withdrawal,
    transaction_id,
)
from casebook.model.files import CRM_JSON, PORTFOLIO_IPS, PORTFOLIO_TAX_PROFILE, REALIZED_CSV, TRANSACTIONS_CSV
from casebook.model.household import TaxUnit
from casebook.model.money import cents, usd
from casebook.model.registry import FigureTable, RegistryEntry
from casebook.plant.a01_backdoor_roth import TAX_YEAR, YEAR_END
from casebook.plant.common import PlantContext, PlantError, Planting, names
from casebook.rules import load_rules

ITEM_TYPE = "niit_threshold"
ZERO = Decimal(0)
TAXABLE = ("joint_taxable", "individual_taxable")
RETIREMENT = ("traditional_ira", "roth_ira", "401k", "inherited_ira")
FIXED_INCOME = "Fixed income"
WAGES = "wages"
# What makes the twin a near miss rather than clean: modified AGI under the threshold by no more than this.
NEAR_MISS_MARGIN = Decimal(25000)
# The rules' suffix for each filing status's NIIT threshold.
NIIT_THRESHOLD = {
    "married_filing_jointly": "niit_threshold_mfj",
    "married_filing_separately": "niit_threshold_mfs",
    "single": "niit_threshold_single",
    "head_of_household": "niit_threshold_hoh",
}


@dataclass(frozen=True)
class Workings:
    unit: TaxUnit
    taxable_ids: tuple[str, ...]
    retirement_ids: tuple[str, ...]
    wages: tuple[tuple[str, str, Decimal], ...]  # person, payer, amount
    dividends: Decimal
    gain: Decimal
    threshold: Decimal
    rate: Decimal

    @property
    def total_wages(self) -> Decimal:
        return sum((amount for _, _, amount in self.wages), ZERO)

    @property
    def net_investment_income(self) -> Decimal:
        return self.dividends + self.gain

    @property
    def modified_agi(self) -> Decimal:
        # Wages plus net investment income: the household has no other income and no adjustments.
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


def _accounts(context: PlantContext, unit: TaxUnit, types: tuple[str, ...]) -> tuple[str, ...]:
    hh = context.script.household
    return tuple(
        a.account_id
        for a in hh.accounts
        if a.account_type in types and set(hh.owners(a.account_id)) <= set(unit.person_ids)
    )


def workings(context: PlantContext, unit: TaxUnit) -> Workings:
    hh, where = context.script.household, context.script.source
    if unit.filing_status not in NIIT_THRESHOLD:
        raise PlantError(f"{where}: no NIIT threshold for filing status {unit.filing_status!r}")
    carried = [c for c in hh.tax_profile.loss_carryforwards if c.tax_unit_id == unit.tax_unit_id]
    if any(c.short_term or c.long_term for c in carried):
        raise PlantError(f"{where}: the NIIT workings here take no capital loss carryforward into {TAX_YEAR}")
    taxable = _accounts(context, unit, TAXABLE)
    retirement = _accounts(context, unit, RETIREMENT)
    # IRA activity is not income here only while nothing comes out of or goes into the IRAs.
    flows = (Contribution, Withdrawal, RequiredDistribution, CharitableDistribution, RothConversion)
    if any(isinstance(e, flows) and e.date.year == TAX_YEAR and e.account_id in retirement for e in context.events):
        raise PlantError(f"{where}: the NIIT workings here take no retirement-account income or deduction")
    rules = load_rules(TAX_YEAR)
    gains = [
        lot.proceeds - lot.cost
        for lot in context.replayed.closed
        if lot.account_id in taxable and lot.sold.year == TAX_YEAR
    ]
    gain = sum(gains, ZERO)
    if gain < 0:
        raise PlantError(f"{where}: the NIIT workings here take a net realized gain, not a net loss")
    return Workings(
        unit=unit,
        taxable_ids=taxable,
        retirement_ids=retirement,
        wages=tuple(
            (i.person_id, i.payer, i.amount)
            for i in hh.income
            if i.kind == WAGES and i.year == TAX_YEAR and i.person_id in unit.person_ids
        ),
        dividends=sum(
            (
                e.amount
                for e in context.events
                if isinstance(e, Dividend) and e.date.year == TAX_YEAR and e.account_id in taxable
            ),
            ZERO,
        ),
        gain=gain,
        threshold=rules.value(NIIT_THRESHOLD[unit.filing_status]),
        rate=rules.value("niit_rate"),
    )


def _salt(unit: TaxUnit) -> tuple[Decimal, Decimal]:
    """The SALT deduction limit and the modified AGI at which it starts to phase down."""
    rules = load_rules(TAX_YEAR)
    suffix = "_mfs" if unit.filing_status == "married_filing_separately" else ""
    return rules.value(f"salt_cap{suffix}"), rules.value(f"salt_phase_down_threshold{suffix}")


def _percent(rate: Decimal) -> str:
    return f"{(rate * 100).normalize():f}%"


def plant_trap(context: PlantContext) -> Planting:
    script = context.script
    assert script.planted is not None
    spec, hh = script.planted, script.household
    unit = next((u for u in hh.tax_units if u.tax_unit_id == spec.details["tax_unit_id"]), None)
    if unit is None:
        raise PlantError(f"{spec.item_id}: {spec.details['tax_unit_id']} is not a tax unit of {hh.household_id}")
    w = workings(context, unit)
    sale_day, security = parse_date(spec.details["sale_date"]), spec.details["security_id"]
    sale = next(
        (
            e
            for e in context.events
            if isinstance(e, Sell)
            and e.date == sale_day
            and e.security_id == security
            and e.account_id in w.taxable_ids
        ),
        None,
    )
    if sale is None or sale.date.year != TAX_YEAR:
        raise PlantError(f"{spec.item_id}: no {TAX_YEAR} sale of {security} on {sale_day} in a taxable account")
    sold = [lot for lot in context.replayed.closed if lot.event_id == sale.event_id]
    sale_gain = sum((lot.proceeds - lot.cost for lot in sold), ZERO)
    if w.modified_agi <= w.threshold:
        raise PlantError(
            f"{spec.item_id}: modified AGI of {usd(w.modified_agi)} is not over the {usd(w.threshold)} NIIT threshold"
        )
    without = w.modified_agi - sale_gain
    if without > w.threshold:
        raise PlantError(
            f"{spec.item_id}: modified AGI is over the threshold without the sale, so the sale is not the trap"
        )
    salt_cap, salt_threshold = _salt(unit)
    if w.modified_agi >= salt_threshold:
        raise PlantError(f"{spec.item_id}: modified AGI reaches the SALT phase-down; the workings take the full cap")
    snapshot = context.snapshot(YEAR_END)
    classes = hh.asset_classes
    bonds_taxable = sorted(
        {lot.security_id for lot in snapshot.lots if lot.account_id in w.taxable_ids}
        & {s for s, c in classes.items() if c == FIXED_INCOME}
    )
    bonds_sheltered = [
        lot
        for lot in snapshot.lots
        if lot.account_id in w.retirement_ids and classes.get(lot.security_id) == FIXED_INCOME
    ]
    if not bonds_taxable or bonds_sheltered or not w.retirement_ids:
        raise PlantError(
            f"{spec.item_id}: the asset-location point needs bonds in a taxable account and none in the IRAs"
        )
    bond_income = sum(
        (
            e.amount
            for e in context.events
            if isinstance(e, Dividend)
            and e.date.year == TAX_YEAR
            and e.account_id in w.taxable_ids
            and e.security_id in bonds_taxable
        ),
        ZERO,
    )
    acquired = sorted({lot.acquired for lot in sold})
    earners = names(hh, unit.person_ids)
    conclusion = (
        f"In {TAX_YEAR} {earners} ({unit.filing_status.replace('_', ' ')}) had {usd(w.total_wages)} of wages "
        f"and, in their taxable accounts {', '.join(w.taxable_ids)}, {usd(w.dividends)} of dividends and a net "
        f"realized gain of "
        f"{usd(w.gain)}. Of that gain, {usd(sale_gain)} came from the sale of {sale.units} units of {security} on "
        f"{sale.date.isoformat()} (transaction {transaction_id(sale.event_id)}), held since "
        f"{acquired[0].isoformat()}. Net investment income is {usd(w.net_investment_income)}; dividends and gains "
        f"inside their retirement accounts ({', '.join(w.retirement_ids)}) are not income. The household has no "
        f"other income and no adjustments to income, so modified AGI is wages plus net investment income: "
        f"{usd(w.modified_agi)}, which is {usd(w.excess)} over the {usd(w.threshold)} threshold for their filing "
        f"status. The sale on {sale.date.isoformat()} put it over: without its gain, modified AGI would have been "
        f"{usd(without)}. "
        f"The net investment income tax of IRC § 1411 is {_percent(w.rate)} of the lesser of net investment income "
        f"and that excess, {usd(w.taxed)}: {usd(w.niit)} for {TAX_YEAR}. The SALT deduction limit of IRC § 164(b) "
        f"applies in full, {usd(salt_cap)}, because modified AGI is below the {usd(salt_threshold)} at which "
        f"§ 164(b)(7) starts to reduce it. Asset location: the taxable accounts hold the bond fund "
        f"{', '.join(bonds_taxable)}, whose {usd(bond_income)} of {TAX_YEAR} dividends is all net investment income "
        f"taxed this year, while the IRAs hold only equity funds; held in an IRA instead, that income would not "
        f"have counted toward modified AGI or net investment income."
    )
    rows: list[tuple[str, str]] = [
        (f"Wages, {hh.person(person).name}, {payer}", usd(amount)) for person, payer, amount in w.wages
    ]
    rows += [
        ("Dividends in the taxable accounts", usd(w.dividends)),
        ("Net realized gain in the taxable accounts", usd(w.gain)),
        (f"of which the sale on {sale.date.isoformat()}", usd(sale_gain)),
        ("Net investment income", usd(w.net_investment_income)),
        ("Modified AGI: wages plus net investment income", usd(w.modified_agi)),
        ("NIIT threshold", usd(w.threshold)),
        ("Modified AGI over the threshold", usd(w.excess)),
        ("Lesser of net investment income and the excess", usd(w.taxed)),
        (f"Net investment income tax at {_percent(w.rate)}", usd(w.niit)),
        ("SALT phase-down threshold", usd(salt_threshold)),
        ("SALT deduction limit", usd(salt_cap)),
        ("Bond fund dividends in the taxable accounts", usd(bond_income)),
    ]
    entry = RegistryEntry(
        item_id=spec.item_id,
        household_id=hh.household_id,
        kind="situation",
        item_type=spec.item_type,
        title="A December sale pushes modified AGI over the net investment income tax threshold",
        sources=(TRANSACTIONS_CSV, REALIZED_CSV, PORTFOLIO_TAX_PROFILE, PORTFOLIO_IPS, CRM_JSON),
        conclusion=conclusion,
        figures=(
            ("Net investment income", usd(w.net_investment_income)),
            ("Modified AGI", usd(w.modified_agi)),
            ("Over the threshold", usd(w.excess)),
            ("Net investment income tax", usd(w.niit)),
        ),
        table=FigureTable(columns=("Working", "Amount"), rows=tuple(rows)),
        known_as_of=YEAR_END,
        references=(
            transaction_id(sale.event_id),
            unit.tax_unit_id,
            *w.taxable_ids,
            *w.retirement_ids,
            *bonds_taxable,
        ),
    )
    return Planting(entries=(entry,))


def check_twin(context: PlantContext, kind: str) -> Planting:
    """A near miss has the same shape, and modified AGI under the threshold by less than the margin."""
    where, hh = context.script.source, context.script.household
    if kind != "near_miss":
        raise PlantError(f"{where}: archetype 2's twin is a near miss, not {kind!r}")
    if len(hh.tax_units) != 1:
        raise PlantError(f"{where}: a near miss has one tax unit")
    w = workings(context, hh.tax_units[0])
    if not w.threshold - NEAR_MISS_MARGIN <= w.modified_agi < w.threshold:
        raise PlantError(
            f"{where}: a near miss has modified AGI under the {usd(w.threshold)} threshold by at most "
            f"{usd(NEAR_MISS_MARGIN)}; it is {usd(w.modified_agi)}"
        )
    return Planting()
