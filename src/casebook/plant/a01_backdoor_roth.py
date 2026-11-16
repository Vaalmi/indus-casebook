"""Archetype 1. Dual-income accumulators: a backdoor Roth conversion taxed pro rata because a
rollover IRA holds pre-tax money (Form 8606). The near-miss twin keeps its pre-tax money in a
former employer's 401(k), which Form 8606 does not count.

Form 8606 Part I and Part II are worked here for any person's 2025 traditional IRAs; archetype 4
uses the same workings.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from casebook.model.events import Contribution, Event, RequiredDistribution, RothConversion, Withdrawal, transaction_id
from casebook.model.files import ACCOUNTS_CSV, CRM_JSON, PORTFOLIO_TAX_PROFILE, TRANSACTIONS_CSV
from casebook.model.money import cents, usd
from casebook.model.registry import FigureTable, RegistryEntry
from casebook.plant.common import PlantContext, PlantError, Planting
from casebook.rules import load_rules

ITEM_TYPE = "backdoor_roth_pro_rata"
ZERO = Decimal(0)
TAX_YEAR = 2025
YEAR_END = date(TAX_YEAR, 12, 31)
TRADITIONAL_IRA = "traditional_ira"
EMPLOYER_PLAN = "401k"
ROLLOVER = "rollover"
# Form 8606 line 10: "Divide line 5 by line 9. Enter the result as a decimal rounded to at least 3 places."
RATIO_PLACES = Decimal("0.001")


@dataclass(frozen=True)
class Form8606:
    """One person's 2025 Form 8606, Part I (nondeductible contributions and basis) and Part II
    (conversions). Contributions made in 2026 for 2025 (line 4) are none: every contribution in the
    book is for the year it is made in."""

    person_id: str
    ira_ids: tuple[str, ...]
    contribution_ids: tuple[str, ...]
    conversion_ids: tuple[str, ...]
    line1: Decimal  # nondeductible contributions for 2025
    line2: Decimal  # basis carried from the 2024 Form 8606, line 14
    line6: Decimal  # value of all traditional IRAs at 31 December 2025
    line7: Decimal  # distributions in 2025, conversions not included
    line8: Decimal  # converted to Roth IRAs in 2025
    line4: Decimal = ZERO

    @property
    def line3(self) -> Decimal:
        return self.line1 + self.line2

    @property
    def line5(self) -> Decimal:
        return self.line3 - self.line4

    @property
    def line9(self) -> Decimal:
        return self.line6 + self.line7 + self.line8

    @property
    def line10(self) -> Decimal:
        ratio = (self.line5 / self.line9).quantize(RATIO_PLACES, rounding=ROUND_HALF_UP)
        return min(ratio, Decimal(1))

    @property
    def line11(self) -> Decimal:
        return cents(self.line8 * self.line10)

    @property
    def line12(self) -> Decimal:
        return cents(self.line7 * self.line10)

    @property
    def line13(self) -> Decimal:
        return self.line11 + self.line12

    @property
    def line14(self) -> Decimal:
        return self.line3 - self.line13

    @property
    def line16(self) -> Decimal:
        return self.line8

    @property
    def line17(self) -> Decimal:
        return self.line11

    @property
    def line18(self) -> Decimal:
        return self.line16 - self.line17

    def table(self) -> FigureTable:
        rows = (
            ("1", "Nondeductible contributions for 2025", usd(self.line1)),
            ("2", "Basis in traditional IRAs carried from the 2024 Form 8606", usd(self.line2)),
            ("3", "Line 1 plus line 2", usd(self.line3)),
            ("4", "Contributions on line 1 made from 1 January to 15 April 2026", usd(self.line4)),
            ("5", "Line 3 less line 4", usd(self.line5)),
            ("6", "Value of all traditional IRAs on 31 December 2025", usd(self.line6)),
            ("7", "Distributions in 2025, conversions not included", usd(self.line7)),
            ("8", "Converted to Roth IRAs in 2025", usd(self.line8)),
            ("9", "Lines 6, 7 and 8 added", usd(self.line9)),
            ("10", "Line 5 divided by line 9, rounded to three places", f"{self.line10:.3f}"),
            ("11", "Nontaxable part of the conversion: line 8 times line 10", usd(self.line11)),
            ("12", "Nontaxable part of the distributions: line 7 times line 10", usd(self.line12)),
            ("13", "Line 11 plus line 12", usd(self.line13)),
            ("14", "Basis carried to 2026: line 3 less line 13", usd(self.line14)),
            ("16", "Amount converted", usd(self.line16)),
            ("17", "Basis in the amount converted: line 11", usd(self.line17)),
            ("18", "Taxable amount: line 16 less line 17", usd(self.line18)),
        )
        return FigureTable(columns=("Form 8606 line", "What it holds", "Amount"), rows=rows)


def owned_accounts(context: PlantContext, person_id: str, account_type: str) -> tuple[str, ...]:
    hh = context.script.household
    return tuple(
        a.account_id for a in hh.accounts if a.account_type == account_type and hh.owners(a.account_id) == (person_id,)
    )


def ira_basis(context: PlantContext, person_id: str) -> Decimal:
    profile = context.script.household.tax_profile
    for entry in profile.ira_basis:
        if entry.person_id == person_id:
            return entry.basis
    raise PlantError(f"{context.script.source}: the tax profile carries no IRA basis for {person_id}")


def _in_year(event: Event) -> bool:
    return event.date.year == TAX_YEAR


def form_8606(context: PlantContext, person_id: str) -> Form8606:
    iras = owned_accounts(context, person_id, TRADITIONAL_IRA)
    if not iras:
        raise PlantError(f"{context.script.source}: {person_id} owns no traditional IRA")
    events = [e for e in context.events if _in_year(e) and e.account_id in iras]
    contributions = [e for e in events if isinstance(e, Contribution)]
    conversions = [e for e in events if isinstance(e, RothConversion)]
    distributions = [e for e in events if isinstance(e, Withdrawal | RequiredDistribution)]
    return Form8606(
        person_id=person_id,
        ira_ids=iras,
        contribution_ids=tuple(transaction_id(e.event_id) for e in contributions),
        conversion_ids=tuple(transaction_id(e.event_id) for e in conversions),
        line1=sum((e.amount for e in contributions), ZERO),
        line2=ira_basis(context, person_id),
        line6=sum((context.value(a, YEAR_END) for a in iras), ZERO),
        line7=-sum((e.amount for e in distributions), ZERO),
        line8=sum((e.amount for e in conversions), ZERO),
    )


def contribution_limit(context: PlantContext, person_id: str) -> Decimal:
    rules = load_rules(TAX_YEAR)
    born = context.script.household.person(person_id).born
    catch_up = rules.value("ira_catch_up") if TAX_YEAR - born.year >= 50 else ZERO
    return rules.value("ira_contribution_limit") + catch_up


def _conversion_days(context: PlantContext, form: Form8606) -> list[RothConversion]:
    return [
        e for e in context.events if isinstance(e, RothConversion) and transaction_id(e.event_id) in form.conversion_ids
    ]


def _backdoor(context: PlantContext, person_id: str) -> tuple[Form8606, RothConversion]:
    """The person's 2025 Form 8606, after checking it shows a backdoor Roth: a nondeductible
    contribution within the limit, then a conversion of it."""
    where = context.script.source
    form = form_8606(context, person_id)
    if form.line1 <= 0:
        raise PlantError(f"{where}: {person_id} made no nondeductible traditional IRA contribution in {TAX_YEAR}")
    if form.line1 > contribution_limit(context, person_id):
        raise PlantError(f"{where}: {person_id}'s {usd(form.line1)} contribution is above the IRA contribution limit")
    conversions = _conversion_days(context, form)
    if not conversions:
        raise PlantError(f"{where}: {person_id} converted nothing to a Roth IRA in {TAX_YEAR}")
    first_contribution = min(e.date for e in context.events if transaction_id(e.event_id) in form.contribution_ids)
    if conversions[0].date < first_contribution:
        raise PlantError(f"{where}: {person_id}'s conversion comes before the contribution it converts")
    return form, conversions[0]


def plant_trap(context: PlantContext) -> Planting:
    script = context.script
    assert script.planted is not None
    spec, hh = script.planted, script.household
    person_id = spec.details["person_id"]
    person = hh.person(person_id).name
    form, conversion = _backdoor(context, person_id)
    contributed_to = next(e for e in context.events if transaction_id(e.event_id) == form.contribution_ids[0])
    rollovers = [
        a for a in form.ira_ids if ROLLOVER in hh.account(a).registration.lower() and context.value(a, YEAR_END) > 0
    ]
    if not rollovers:
        raise PlantError(f"{spec.item_id}: {person} has no rollover IRA holding money on {YEAR_END}")
    if form.line18 <= form.line17:
        raise PlantError(f"{spec.item_id}: most of {person}'s conversion is not taxable, so there is no trap")
    rollover_value = sum((context.value(a, YEAR_END) for a in rollovers), ZERO)
    conclusion = (
        f"{person} made a {usd(form.line1)} nondeductible contribution to the traditional IRA "
        f"{contributed_to.account_id} on {contributed_to.date.isoformat()} and converted {usd(form.line8)} to the Roth "
        f"IRA {conversion.to_account_id} on {conversion.date.isoformat()}: a backdoor Roth. The conversion is not "
        f"tax-free. Under the pro-rata rule of IRC § 408(d)(2), which Form 8606 Part I applies, the nontaxable share "
        f"of a conversion is the person's basis over the value of all their traditional IRAs, and the Form 8606 "
        f"instructions count every traditional IRA on 31 December, the rollover IRA {', '.join(rollovers)} included "
        f"({usd(rollover_value)} on {YEAR_END.isoformat()}). With {usd(form.line5)} of basis (line 5) against "
        f"{usd(form.line9)} (line 9), line 10 is {form.line10:.3f}: {usd(form.line11)} of the conversion is "
        f"nontaxable and {usd(form.line18)} is taxable income for {TAX_YEAR} (line 18). The other "
        f"{usd(form.line14)} of basis is not lost; it carries to 2026 (line 14)."
    )
    entry = RegistryEntry(
        item_id=spec.item_id,
        household_id=hh.household_id,
        kind="situation",
        item_type=spec.item_type,
        title="Backdoor Roth taxed pro rata: a rollover IRA holds pre-tax money at year end",
        sources=(TRANSACTIONS_CSV, ACCOUNTS_CSV, PORTFOLIO_TAX_PROFILE, CRM_JSON),
        conclusion=conclusion,
        figures=(
            ("Converted", usd(form.line8)),
            ("Nontaxable part (Form 8606 line 17)", usd(form.line17)),
            ("Taxable amount (Form 8606 line 18)", usd(form.line18)),
            ("Basis carried to 2026 (Form 8606 line 14)", usd(form.line14)),
        ),
        table=form.table(),
        known_as_of=YEAR_END,
        references=(*form.contribution_ids, *form.conversion_ids, *form.ira_ids, conversion.to_account_id, person_id),
    )
    return Planting(entries=(entry,))


def check_twin(context: PlantContext, kind: str) -> Planting:
    """A near miss makes the same backdoor Roth, with the pre-tax money in a 401(k), which Form 8606
    line 6 does not count, and no traditional IRA value left at year end."""
    if kind != "near_miss":
        raise PlantError(f"{context.script.source}: archetype 1's twin is a near miss, not {kind!r}")
    hh = context.script.household
    converters = {hh.owners(e.account_id)[0] for e in context.events if isinstance(e, RothConversion) and _in_year(e)}
    if len(converters) != 1:
        raise PlantError(f"{context.script.source}: a near miss has one person making a backdoor Roth")
    person_id = converters.pop()
    form, _ = _backdoor(context, person_id)
    plans = owned_accounts(context, person_id, EMPLOYER_PLAN)
    pre_tax = sum((context.value(a, YEAR_END) for a in plans), ZERO)
    if pre_tax <= form.line8:
        raise PlantError(
            f"{context.script.source}: a near miss holds a large pre-tax balance outside IRAs; "
            f"{person_id}'s 401(k)s held {usd(pre_tax)} on {YEAR_END}"
        )
    if form.line6 != 0:
        raise PlantError(
            f"{context.script.source}: a near miss has no traditional IRA value at year end; "
            f"{person_id}'s held {usd(form.line6)} on {YEAR_END}"
        )
    return Planting()
