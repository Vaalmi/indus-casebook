"""Archetype 5 drawn: a first-RMD retiree with several IRAs and a former employer's 401(k). The
trap takes one distribution from an IRA for every account's RMD added together, so the 401(k)'s own
RMD is missed; the near-miss twin takes the IRAs' RMDs together from one IRA and the 401(k)'s from
the 401(k), leaving another IRA with no distribution.

The helpers archetypes 6 and 7 share live here too: an account's 31 December 2024 balance, worked
out from its drawn holdings exactly as the opening lots are, and a sale that raises the cash a
distribution pays out.
"""

from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from casebook.generate.background.common import (
    BOND_FUNDS,
    EMPLOYERS,
    INTERNATIONAL_FUNDS,
    MUNI_FUNDS,
    SURNAMES,
    US_FUNDS,
    Ids,
    PairSpec,
    account_script,
    advisory,
    amount,
    born_between,
    day_between,
    fit_ips,
    holding_rows,
    household,
    person,
    with_social_security,
)
from casebook.generate.script import AccountScript, Activity, HouseholdScript, PlantedSpec, TwinSpec
from casebook.model.dates import PRIOR_YEAR_END, add_weekdays
from casebook.model.household import Account, Beneficiary, BillingGroup, CrmActivity, Person, TaxUnit
from casebook.model.money import cents, usd
from casebook.rules import load_rules
from casebook.securities.market import Market

ITEM_TYPE = "first_rmd_401k_shortfall"
DISTRIBUTION_YEAR = 2025
UNIFORM = "uniform_lifetime"
# Days between the sale that raises the cash and the distribution that pays it out, so the sale
# has settled (T+1) with a day to spare.
SETTLE_WEEKDAYS = 3
WITHHOLDING_PCTS = (0, 10, 20)
# Holdings drawn to the nearest $250, so a background figure rarely lands on a featured round one.
STEP = 250


def opening_balance(account: AccountScript, market: Market) -> Decimal:
    """An account's 31 December 2024 balance: each holding's whole units (its drawn value over that
    day's price, rounded down, as the opening lots are) at that day's price, plus cash."""
    total = account.cash
    for holding in account.holdings:
        price = market.price(holding.security_id, PRIOR_YEAR_END)
        units = (holding.value / price).quantize(Decimal(1), rounding=ROUND_FLOOR)
        total += cents(units * price)
    return total


def raise_cash(account: AccountScript, needed: Decimal, day: date, market: Market) -> Activity:
    """A sale of the account's largest holding on `day` whose proceeds cover `needed`."""
    largest = max(account.holdings, key=lambda h: h.value)
    price = market.price(largest.security_id, day)
    units = (needed / price).quantize(Decimal(1), rounding=ROUND_CEILING)
    return Activity("sell", day, account.account_id, security_id=largest.security_id, units=units)


def whole_dollars_up(value: Decimal) -> Decimal:
    return value.quantize(Decimal(1), rounding=ROUND_CEILING).quantize(Decimal("0.01"))


def withheld(value: Decimal, pct: int) -> Decimal:
    return cents(value * pct / 100)


def first(p: Person) -> str:
    return p.name.split()[0]


def _draw(spec: PairSpec, household_id: str, trap: bool, market: Market) -> HouseholdScript:
    rng, ids = spec.rng, Ids(household_id)
    rules = load_rules(DISTRIBUTION_YEAR)
    surname = rng.choice(SURNAMES)
    # Reaches 73 in 2025, the first distribution year.
    owner = person(rng, ids, 1, "primary", born_between(rng, date(1952, 1, 1), date(1952, 12, 31)), surname)
    married = rng.random() < 0.7
    if married:
        # Not more than ten years younger, so the Uniform Lifetime table applies.
        other = person(rng, ids, 2, "spouse", born_between(rng, date(1950, 6, 1), date(1962, 12, 31)), surname)
    else:
        relationship = "daughter" if rng.random() < 0.5 else "son"
        other = person(rng, ids, 2, relationship, born_between(rng, date(1974, 1, 1), date(1990, 12, 31)), surname)
    o = first(owner)
    taxable_opened = day_between(rng, date(2012, 1, 2), date(2019, 12, 31))
    if married:
        taxable = Account(ids.account(1), "joint_taxable", "Joint tenants with right of survivorship", taxable_opened)
        taxable_owners: tuple[str, ...] = (owner.person_id, other.person_id)
    else:
        taxable = Account(ids.account(1), "individual_taxable", f"Individual, {owner.name}", taxable_opened)
        taxable_owners = (owner.person_id,)
    employer = rng.choice(EMPLOYERS)
    plan_opened = day_between(rng, date(1990, 1, 2), date(2004, 12, 31))
    # Two IRAs, not three: the planter's conclusion speaks of "the three accounts' RMDs".
    ira_opened = [
        day_between(rng, date(1995, 1, 2), date(2008, 12, 31)),
        day_between(rng, date(2009, 1, 2), date(2018, 12, 31)),
    ]
    iras = [
        Account(ids.account(2), "traditional_ira", f"Traditional IRA, {owner.name}", ira_opened[0]),
        Account(ids.account(3), "traditional_ira", f"Traditional IRA (rollover), {owner.name}", ira_opened[1]),
    ]
    plan = Account(
        ids.account(4),
        "401k",
        f"{employer} 401(k) Plan, {owner.name} (former employee)",
        plan_opened,
    )

    us, us2 = rng.sample(US_FUNDS, 2)
    intl = rng.choice(INTERNATIONAL_FUNDS)
    bond, bond2 = rng.sample(BOND_FUNDS, 2)
    muni = rng.choice(MUNI_FUNDS)
    scripts = [
        account_script(
            taxable.account_id,
            amount(rng, 9000, 34000, STEP),
            holding_rows(
                rng,
                ids,
                1,
                [
                    (us, amount(rng, 140000, 330000, STEP)),
                    (intl, amount(rng, 40000, 110000, STEP)),
                    (muni, amount(rng, 70000, 190000, STEP)),
                ],
                acquired_from=taxable_opened,
            ),
        ),
        account_script(
            iras[0].account_id,
            amount(rng, 7000, 16000, STEP),
            holding_rows(
                rng,
                ids,
                2,
                [
                    (us, amount(rng, 190000, 360000, STEP)),
                    (bond, amount(rng, 140000, 280000, STEP)),
                    (intl, amount(rng, 40000, 100000, STEP)),
                ],
                acquired_from=ira_opened[0],
                basis=(100, 100),
            ),
        ),
    ]
    for k, ira in enumerate(iras[1:], start=1):
        scripts.append(
            account_script(
                ira.account_id,
                amount(rng, 5000, 10000, STEP),
                holding_rows(
                    rng,
                    ids,
                    2 + k,
                    [(us2, amount(rng, 60000, 160000, STEP)), (bond2, amount(rng, 40000, 120000, STEP))],
                    acquired_from=ira_opened[k],
                    basis=(100, 100),
                ),
            )
        )
    scripts.append(
        account_script(
            plan.account_id,
            amount(rng, 5000, 12000, STEP),
            holding_rows(
                rng,
                ids,
                4,
                [(us2, amount(rng, 110000, 260000, STEP)), (bond2, amount(rng, 80000, 180000, STEP))],
                acquired_from=max(plan_opened, date(2005, 1, 3)),
                basis=(100, 100),
            ),
        )
    )
    by_id = {s.account_id: s for s in scripts}

    # Each account's 2025 RMD: its 31 December 2024 balance over the Uniform Lifetime factor at 73.
    factor = rules.factor(UNIFORM, DISTRIBUTION_YEAR - owner.born.year)
    ira_rmds = [cents(opening_balance(by_id[a.account_id], market) / factor) for a in iras]
    ira_rmd = sum(ira_rmds, Decimal(0))
    plan_rmd = cents(opening_balance(by_id[plan.account_id], market) / factor)

    retired = day_between(rng, date(2014, 1, 2), date(2021, 12, 31))
    crm: list[CrmActivity] = [
        CrmActivity(
            ids.activity(1),
            retired,
            "retirement",
            f"{owner.name} retired from {employer}. The 401(k) stays in the plan as a former employee's account.",
        )
    ]
    activity: list[Activity] = []
    pct = rng.choice(WITHHOLDING_PCTS)
    held = f"with {pct}% federal tax withheld" if pct else "with no federal tax withheld"
    if trap:
        total = ira_rmd + plan_rmd
        sell_day = day_between(rng, date(2025, 9, 1), date(2026, 3, 18))
        paid_on = add_weekdays(sell_day, SETTLE_WEEKDAYS)
        crm.append(
            CrmActivity(
                ids.activity(2),
                day_between(rng, date(2025, 8, 4), sell_day),
                "distribution_instruction",
                f"{owner.name} signed a distribution form for the 2025 required minimum distributions of all "
                f"three retirement accounts added together: one payment of {usd(total)} from IRA "
                f"{iras[0].account_id}, {held}.",
            )
        )
        activity += [
            raise_cash(by_id[iras[0].account_id], total, sell_day, market),
            Activity("rmd", paid_on, iras[0].account_id, amount=total, tax_year=2025, withheld=withheld(total, pct)),
        ]
    else:
        from_plan, from_iras = whole_dollars_up(plan_rmd), whole_dollars_up(ira_rmd)
        plan_sale = day_between(rng, date(2025, 6, 2), date(2025, 12, 12))
        ira_sale = day_between(rng, date(2025, 9, 1), date(2026, 3, 18))
        crm += [
            CrmActivity(
                ids.activity(2),
                day_between(rng, date(2025, 5, 1), plan_sale),
                "distribution_instruction",
                f"{owner.name} signed a distribution form with the 401(k) plan for its 2025 required minimum "
                f"distribution of {usd(from_plan)}, paid from the plan, {held}.",
            ),
            CrmActivity(
                ids.activity(3),
                day_between(rng, date(2025, 8, 4), ira_sale),
                "distribution_instruction",
                f"{owner.name} signed a distribution form for the 2025 required minimum distributions of both "
                f"IRAs, {usd(from_iras)} taken together from IRA {iras[0].account_id}, {held}.",
            ),
        ]
        activity += [
            raise_cash(by_id[plan.account_id], from_plan, plan_sale, market),
            Activity(
                "rmd",
                add_weekdays(plan_sale, SETTLE_WEEKDAYS),
                plan.account_id,
                amount=from_plan,
                tax_year=2025,
                withheld=withheld(from_plan, pct),
            ),
            raise_cash(by_id[iras[0].account_id], from_iras, ira_sale, market),
            Activity(
                "rmd",
                add_weekdays(ira_sale, SETTLE_WEEKDAYS),
                iras[0].account_id,
                amount=from_iras,
                tax_year=2025,
                withheld=withheld(from_iras, pct),
            ),
        ]
    added = day_between(rng, date(2025, 2, 3), date(2025, 6, 27))
    top_up = cents(amount(rng, 5000, 18000, STEP))
    activity += [
        Activity("contribution", added, taxable.account_id, amount=top_up),
        Activity(
            "buy",
            add_weekdays(added, 2),
            taxable.account_id,
            security_id=us,
            units=(top_up * Decimal("0.9") / market.price(us, add_weekdays(added, 2))).quantize(
                Decimal(1), rounding=ROUND_FLOOR
            ),
        ),
        Activity(
            "withdrawal",
            day_between(rng, date(2026, 1, 5), date(2026, 4, 10)),
            taxable.account_id,
            amount=cents(amount(rng, 4000, 12000, STEP)),
        ),
    ]
    activity.sort(key=lambda a: a.day)

    retirement = [*iras, plan]
    beneficiaries = tuple(
        Beneficiary(
            a.account_id,
            "primary",
            other.name,
            other.relationship,
            Decimal(100),
            other.person_id,
            a.opened,
        )
        for a in retirement
    )
    accounts = [(taxable, taxable_owners), *((a, (owner.person_id,)) for a in retirement)]
    all_ids = tuple(a.account_id for a, _ in accounts)
    family = [owner, other]
    parties = taxable_owners
    tax_units = (
        [TaxUnit(ids.tax_unit(1), "married_filing_jointly", (owner.person_id, other.person_id))]
        if married
        else [
            TaxUnit(ids.tax_unit(1), "single", (owner.person_id,)),
            TaxUnit(ids.tax_unit(2), "single", (other.person_id,)),
        ]
    )
    hh = household(
        ids,
        f"{surname} household",
        5,
        family,
        accounts,
        tax_units,
        [BillingGroup(ids.billing_group(1), "FS-STD", all_ids)],
        [advisory(ids, 1, family, parties, all_ids, taxable_opened)],
        configured=taxable_opened,
        beneficiaries=beneficiaries,
        crm_activities=tuple(crm),
    )
    planted = twin = None
    if trap:
        planted = PlantedSpec(spec.item_id, ITEM_TYPE, {})
    else:
        unpaid = " and ".join(a.account_id for a in iras[1:])
        twin = TwinSpec(
            "near_miss",
            f"A near miss. {o} turned 73 in 2025, the first distribution year, and IRA {unpaid} shows no 2025 "
            f"distribution, which looks like a missed first RMD. But the IRAs' RMDs, {usd(ira_rmd)} together, were "
            f"taken from IRA {iras[0].account_id}, which is allowed because IRA RMDs may be aggregated, and the "
            f"401(k)'s own RMD of {usd(plan_rmd)}, which may not be aggregated with the IRAs', was paid from the "
            "401(k). Nothing is short.",
        )
    return HouseholdScript(
        source=f"background/{household_id}",
        household=hh,
        pair=spec.pair,
        role="trap" if trap else "twin",
        accounts=tuple(scripts),
        activity=tuple(activity),
        planted=planted,
        twin=twin,
        background=True,
    )


def generate_pair(spec: PairSpec, market: Market) -> tuple[HouseholdScript, HouseholdScript]:
    trap = fit_ips(_draw(spec, spec.trap_id, True, market), market)
    twin = fit_ips(_draw(spec, spec.twin_id, False, market), market)
    return with_social_security(spec.rng, trap), with_social_security(spec.rng, twin)
