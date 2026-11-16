"""Archetype 5. First-RMD retiree: the first required distribution across several IRAs and a 401(k).

The trap takes one distribution from an IRA for all three accounts' RMDs, which covers the IRAs
(their RMDs may be aggregated) but not the 401(k), whose RMD must come from the plan. The near-miss
twin takes the IRAs' RMDs together from one IRA and the 401(k)'s from the 401(k).

The RMD helpers the archetypes 6 and 7 planters share live here too.
"""

import calendar
import dataclasses
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from casebook.model.dates import PRIOR_YEAR_END, SCENARIO_DATE
from casebook.model.events import CharitableDistribution, RequiredDistribution, Withdrawal, transaction_id
from casebook.model.files import ACCOUNTS_CSV, BENEFICIARIES_CSV, CASH_CSV, CRM_JSON, POSITIONS_CSV, TRANSACTIONS_CSV
from casebook.model.household import Household
from casebook.model.money import cents, usd
from casebook.model.registry import FigureTable, RegistryEntry
from casebook.plant.common import PlantContext, PlantError, Planting, account_value
from casebook.rules import Rules, load_rules

ITEM_TYPE = "first_rmd_401k_shortfall"
ZERO = Decimal(0)
IRA = "traditional_ira"
PLAN = "401k"
DISTRIBUTION_YEAR = PRIOR_YEAR_END.year + 1

# Legal facts the 2025 rules table does not hold, named once here with their sources.
# The required beginning date: 1 April of the year after the year the owner reaches the applicable
# age (26 U.S.C. § 401(a)(9)(C)(i); for an IRA, § 408(a)(6)); for a plan, the year after the later
# of that year and retirement (§ 401(a)(9)(C)(i)(II)).
RBD_MONTH, RBD_DAY = 4, 1
# The applicable age before the 2025 table's 73 (which covers those born 1951 to 1959): 70½ for
# those born before 1 July 1949 (§ 401(a)(9)(C)(i) before 2020); 72 for those born from 1 July 1949
# to 1950 (SECURE Act § 114, Pub. L. 116-94); 75 from 1960 (§ 401(a)(9)(C)(v)(II)).
AGE_72_FROM, AGE_73_FROM, AGE_75_FROM = date(1949, 7, 1), date(1951, 1, 1), date(1960, 1, 1)
AGE_70_HALF_YEARS, AGE_72 = 70, 72
HALF_YEAR_MONTHS = 6
# The Uniform Lifetime table applies unless the sole beneficiary is a spouse more than ten years
# younger, who takes the Joint and Last Survivor table (26 CFR 1.401(a)(9)-5(c)(2)), which the
# rules table does not hold.
JOINT_TABLE_YEARS = 10
UNIFORM = "uniform_lifetime"


def age_in(born: date, year: int) -> int:
    """Age on the birthday in `year`, the age the RMD tables use."""
    return year - born.year


def half_birthday(born: date, years: int) -> date:
    """The day six calendar months after the birthday at `years`: 70½ is half_birthday(born, 70)."""
    month = born.month + HALF_YEAR_MONTHS
    year = born.year + years + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return date(year, month, min(born.day, calendar.monthrange(year, month)[1]))


def required_beginning_date(rules: Rules, born: date) -> date:
    """An IRA owner's required beginning date, from the applicable age for their birth date."""
    if born >= AGE_75_FROM:
        raise PlantError(f"an owner born {born.isoformat()} has applicable age 75, which no featured household uses")
    if born >= AGE_73_FROM:
        return date(born.year + int(rules.value("rmd_age")) + 1, RBD_MONTH, RBD_DAY)
    if born >= AGE_72_FROM:
        return date(born.year + AGE_72 + 1, RBD_MONTH, RBD_DAY)
    return date(half_birthday(born, AGE_70_HALF_YEARS).year + 1, RBD_MONTH, RBD_DAY)


def prior_year_end_balance(context: PlantContext, account_id: str) -> Decimal:
    """The 31 December 2024 balance an RMD is figured on: the opening positions at that day's prices, plus cash."""
    return account_value(dataclasses.replace(context.replayed.opening, day=PRIOR_YEAR_END), account_id, context.market)


type Payout = RequiredDistribution | CharitableDistribution | Withdrawal


def distributions_for(context: PlantContext, account_id: str, year: int, by: date) -> tuple[Payout, ...]:
    """What an account paid out toward `year`'s RMD by `by`: distributions coded for that year,
    and charitable distributions and withdrawals made in it."""
    found: list[Payout] = []
    for event in context.events:
        if event.account_id != account_id or event.date > by:
            continue
        if isinstance(event, RequiredDistribution):
            if event.tax_year == year:
                found.append(event)
        elif isinstance(event, CharitableDistribution | Withdrawal) and event.date.year == year:
            found.append(event)
    return tuple(found)


def gross(events: tuple[Payout, ...]) -> Decimal:
    return sum((-e.amount for e in events), ZERO)


def refuse_joint_table(hh: Household, account_id: str, owner_born: date) -> None:
    primaries = [b for b in hh.beneficiaries if b.account_id == account_id and b.designation == "primary"]
    if len(primaries) == 1 and primaries[0].person_id is not None and primaries[0].relationship == "spouse":
        spouse = hh.person(primaries[0].person_id)
        if spouse.born.year - owner_born.year > JOINT_TABLE_YEARS:
            raise PlantError(
                f"{account_id}: the sole beneficiary is a spouse more than {JOINT_TABLE_YEARS} years younger, "
                "so the Joint and Last Survivor table applies, which the rules table does not hold"
            )


@dataclass(frozen=True)
class AccountRmd:
    account_id: str
    account_type: str
    balance: Decimal
    age: int
    factor: Decimal
    rmd: Decimal
    paid: tuple[Payout, ...]

    @property
    def taken(self) -> Decimal:
        return gross(self.paid)


def uniform_rmd(context: PlantContext, rules: Rules, account_id: str, owner_born: date, by: date) -> AccountRmd:
    hh = context.script.household
    refuse_joint_table(hh, account_id, owner_born)
    balance = prior_year_end_balance(context, account_id)
    age = age_in(owner_born, DISTRIBUTION_YEAR)
    factor = rules.factor(UNIFORM, age)
    paid = distributions_for(context, account_id, DISTRIBUTION_YEAR, by)
    return AccountRmd(
        account_id, hh.account(account_id).account_type, balance, age, factor, cents(balance / factor), paid
    )


@dataclass(frozen=True)
class FirstYear:
    owner_id: str
    rbd: date
    iras: tuple[AccountRmd, ...]
    plans: tuple[AccountRmd, ...]

    @property
    def ira_rmd(self) -> Decimal:
        return sum((a.rmd for a in self.iras), ZERO)

    @property
    def ira_taken(self) -> Decimal:
        return sum((a.taken for a in self.iras), ZERO)


def _first_year(context: PlantContext) -> FirstYear:
    """The owner of the 401(k), in their first distribution year, and each of their accounts' RMD."""
    hh, rules = context.script.household, load_rules(DISTRIBUTION_YEAR)
    plan_owners = {o for a in hh.accounts if a.account_type == PLAN for o in hh.owners(a.account_id)}
    if len(plan_owners) != 1:
        raise PlantError(f"{hh.household_id}: archetype 5 needs one owner of a 401(k), not {len(plan_owners)}")
    owner_id = plan_owners.pop()
    owner = hh.person(owner_id)
    first = owner.born.year + int(rules.value("rmd_age"))
    if first != DISTRIBUTION_YEAR:
        raise PlantError(
            f"{hh.household_id}: {owner.name} reaches {rules.value('rmd_age')} in {first}, "
            f"so {DISTRIBUTION_YEAR} is not the first distribution year"
        )
    if any(i.person_id == owner_id and i.kind == "wages" and i.year == DISTRIBUTION_YEAR for i in hh.income):
        raise PlantError(
            f"{hh.household_id}: {owner.name} has {DISTRIBUTION_YEAR} wages, so the plan's required beginning "
            "date may wait for retirement"
        )
    rbd = required_beginning_date(rules, owner.born)
    owned = [a for a in hh.accounts if hh.owners(a.account_id) == (owner_id,)]
    iras = tuple(uniform_rmd(context, rules, a.account_id, owner.born, rbd) for a in owned if a.account_type == IRA)
    plans = tuple(uniform_rmd(context, rules, a.account_id, owner.born, rbd) for a in owned if a.account_type == PLAN)
    if len(iras) < 2:
        raise PlantError(f"{hh.household_id}: archetype 5 needs at least two traditional IRAs for {owner.name}")
    return FirstYear(owner_id, rbd, iras, plans)


def _table(year: FirstYear) -> FigureTable:
    by = year.rbd.isoformat()
    return FigureTable(
        columns=(
            "Account",
            "Type",
            "Balance on 2024-12-31",
            f"Age in {DISTRIBUTION_YEAR}",
            "Uniform Lifetime factor",
            f"{DISTRIBUTION_YEAR} RMD",
            f"Taken by {by}",
        ),
        rows=tuple(
            (a.account_id, a.account_type, usd(a.balance), str(a.age), str(a.factor), usd(a.rmd), usd(a.taken))
            for a in (*year.iras, *year.plans)
        ),
    )


def plant_trap(context: PlantContext) -> Planting:
    script = context.script
    assert script.planted is not None
    hh, spec = script.household, script.planted
    year = _first_year(context)
    owner = hh.person(year.owner_id)
    if year.ira_taken < year.ira_rmd:
        raise PlantError(f"{spec.item_id}: the IRAs are short as well, which is not this planted item")
    short = [p for p in year.plans if p.taken < p.rmd]
    if not short:
        raise PlantError(f"{spec.item_id}: every 401(k) paid its own {DISTRIBUTION_YEAR} RMD, so none was missed")
    if any(gross(distributions_for(context, p.account_id, DISTRIBUTION_YEAR, SCENARIO_DATE)) >= p.rmd for p in short):
        raise PlantError(f"{spec.item_id}: the 401(k)'s RMD was made up by {SCENARIO_DATE}, so it is not outstanding")
    paid = [e for a in year.iras for e in a.paid]
    shortfall = sum((p.rmd - p.taken for p in short), ZERO)
    excess = year.ira_taken - year.ira_rmd
    ira_list = " and ".join(f"{a.account_id} {usd(a.rmd)}" for a in year.iras)
    paid_list = "; ".join(
        f"{usd(-e.amount)} from {e.account_id} on {e.date.isoformat()} ({transaction_id(e.event_id)})" for e in paid
    )
    plan_list = " and ".join(f"{p.account_id}, registered as '{hh.account(p.account_id).registration}'," for p in short)
    factor = year.iras[0].factor
    conclusion = (
        f"{owner.name}, born {owner.born.isoformat()}, reaches the RMD age of "
        f"{load_rules(DISTRIBUTION_YEAR).value('rmd_age')} in {DISTRIBUTION_YEAR} (26 U.S.C. § 401(a)(9)(C)), so "
        f"{DISTRIBUTION_YEAR} is the first distribution year and its required minimum distributions were due by the "
        f"required beginning date, {year.rbd.isoformat()}. Each account's RMD is its 31 December 2024 balance divided "
        f"by the Uniform Lifetime factor for age {year.iras[0].age}, {factor}. The IRAs owe {ira_list}, "
        f"{usd(year.ira_rmd)} together. IRA RMDs may be added together and taken from any of the owner's IRAs "
        f"(26 CFR 1.408-8), and {paid_list} covers them, by {usd(excess)} more than they need. The 401(k) "
        f"{plan_list} owes {usd(sum((p.rmd for p in short), ZERO))}, which must be paid from the plan itself: an IRA "
        f"distribution cannot meet a 401(k)'s RMD. Nothing was paid from the 401(k) by {year.rbd.isoformat()} or by "
        f"{SCENARIO_DATE.isoformat()}, so its {DISTRIBUTION_YEAR} RMD of {usd(shortfall)} was missed, though the "
        f"custodian's 'Required minimum distribution for {DISTRIBUTION_YEAR}', for the three accounts' RMDs added "
        "together, makes the year look complete. The shortfall is subject to the excise tax of 26 U.S.C. § 4974(a), "
        "reported on Form 5329, which is reduced if the shortfall is distributed within the correction window of "
        "§ 4974(e) and may be waived for reasonable error under § 4974(d). The plan should pay the "
        f"{usd(shortfall)} now, apart from the {DISTRIBUTION_YEAR + 1} RMD due by {DISTRIBUTION_YEAR + 1}-12-31; the "
        "IRA's excess does not count toward it."
    )
    entry = RegistryEntry(
        item_id=spec.item_id,
        household_id=hh.household_id,
        kind="situation",
        item_type=spec.item_type,
        title="First RMD: the IRAs are covered together, the 401(k)'s own RMD was missed",
        sources=(ACCOUNTS_CSV, POSITIONS_CSV, CASH_CSV, TRANSACTIONS_CSV, BENEFICIARIES_CSV, CRM_JSON),
        conclusion=conclusion,
        figures=(
            (f"{DISTRIBUTION_YEAR} RMD, IRAs together", usd(year.ira_rmd)),
            ("Taken from the IRAs", usd(year.ira_taken)),
            (f"{DISTRIBUTION_YEAR} RMD, 401(k)", usd(sum((p.rmd for p in year.plans), ZERO))),
            ("Taken from the 401(k)", usd(sum((p.taken for p in year.plans), ZERO))),
            ("401(k) RMD missed", usd(shortfall)),
            ("Required beginning date", year.rbd.isoformat()),
        ),
        table=_table(year),
        known_as_of=year.rbd + timedelta(days=1),
        references=(
            year.owner_id,
            *(a.account_id for a in (*year.iras, *year.plans)),
            *(transaction_id(e.event_id) for e in paid),
        ),
    )
    return Planting(entries=(entry,))


def check_twin(context: PlantContext, kind: str) -> Planting:
    """A near miss: an IRA shows no distribution, but the IRAs together and each 401(k) on its own are met."""
    hh = context.script.household
    if kind != "near_miss":
        raise PlantError(f"{hh.household_id}: archetype 5's twin is a near miss, not {kind!r}")
    year = _first_year(context)
    if year.ira_taken < year.ira_rmd:
        raise PlantError(
            f"{hh.household_id}: the IRAs paid {usd(year.ira_taken)} of their {usd(year.ira_rmd)} RMD by {year.rbd}"
        )
    for plan in year.plans:
        if plan.taken < plan.rmd:
            raise PlantError(
                f"{hh.household_id}: 401(k) {plan.account_id} paid {usd(plan.taken)} of its {usd(plan.rmd)} RMD "
                f"by {year.rbd}"
            )
    if all(a.paid for a in year.iras):
        raise PlantError(f"{hh.household_id}: every IRA paid a distribution, so nothing looks skipped")
    return Planting()
