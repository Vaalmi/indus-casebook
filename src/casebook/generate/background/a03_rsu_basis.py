"""Archetype 3 drawn: an executive's RSU releases booked at no cost, with the employer stock above
the IPS limit (trap), and the same releases booked at their value, within the limit (clean twin)."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from casebook.generate.background.common import (
    BOND_FUNDS,
    EMPLOYERS,
    INTERNATIONAL_FUNDS,
    STOCKS,
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
)
from casebook.generate.script import AccountScript, Activity, HouseholdScript, PlantedSpec, TwinSpec
from casebook.generate.simulate import simulate
from casebook.model.dates import SCENARIO_DATE, add_weekdays, is_weekday
from casebook.model.household import Account, Beneficiary, BillingGroup, CrmActivity, Income, TaxUnit
from casebook.model.money import cents, fmt, usd
from casebook.plant import PlantError
from casebook.plant.a03_rsu_basis import ITEM_TYPE, RELEASE_CONFIRMATION, WAGES
from casebook.plant.common import account_value
from casebook.replay import replay
from casebook.rules import load_rules
from casebook.securities.market import Market
from casebook.securities.master import by_id, load_master

ZERO = Decimal(0)
# The featured pair's employers, left to it so a background pair cannot be matched to it by its stock.
FEATURED_EMPLOYERS = ("SEC-0028", "SEC-0030")
EMPLOYER_STOCKS = tuple(s for s in STOCKS if s not in FEATURED_EMPLOYERS)
# IPS concentration limits an advisor writes, from which the trap's is chosen.
ROUND_LIMITS = tuple(Decimal(p) for p in ("0.10", "0.15", "0.20", "0.25", "0.30"))
# A day past the wash-sale window.
WINDOW = timedelta(days=int(load_rules().value("wash_sale_days")) + 1)
LAST_SALE = date(2025, 12, 19)
# The employer stock clears its limit, and every other holding stays under it, by these margins.
ABOVE, BELOW = Decimal("0.03"), Decimal("0.02")
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _on_or_after(day: date) -> date:
    while not is_weekday(day):
        day += timedelta(days=1)
    return day


def _shares(script: HouseholdScript, market: Market) -> dict[str, Decimal]:
    """Each security's share of the household on the scenario date."""
    held = replay(simulate(script, market).events, (SCENARIO_DATE,)).snapshots[SCENARIO_DATE]
    by_security: dict[str, Decimal] = defaultdict(lambda: ZERO)
    total = ZERO
    for account in script.household.accounts:
        total += account_value(held, account.account_id, market)
        for security, units in held.holdings(account.account_id).items():
            by_security[security] += cents(units * market.price(security, SCENARIO_DATE))
    return {security: value / total for security, value in by_security.items()}


def _draw(spec: PairSpec, market: Market, household_id: str, trap: bool) -> HouseholdScript:
    rng, ids = spec.rng, Ids(household_id)
    surname = rng.choice(SURNAMES)
    executive = person(rng, ids, 1, "primary", born_between(rng, date(1966, 1, 1), date(1985, 12, 31)), surname)
    spouse_born = born_between(rng, date(1964, 1, 1), date(1987, 12, 31))
    spouse = person(rng, ids, 2, "spouse", spouse_born, surname)
    while spouse.name == executive.name:
        spouse = person(rng, ids, 2, "spouse", spouse_born, surname)
    first = executive.name.split()[0]
    employer = rng.choice(EMPLOYER_STOCKS)
    alias = by_id(load_master())[employer].alias

    joint_opened = day_between(rng, date(2006, 1, 2), date(2018, 12, 31))
    plan_opened = day_between(rng, max(joint_opened, date(2016, 1, 4)), date(2022, 6, 30))
    joint = Account(ids.account(1), "joint_taxable", "Joint tenants with right of survivorship", joint_opened)
    plan = Account(
        ids.account(2), "individual_taxable", f"Individual, {executive.name} (stock plan account)", plan_opened
    )
    retirement = Account(
        ids.account(3), "401k", f"401(k), {executive.name}", day_between(rng, date(2005, 1, 3), plan_opened)
    )
    accounts = [
        (joint, (executive.person_id, spouse.person_id)),
        (plan, (executive.person_id,)),
        (retirement, (executive.person_id,)),
    ]
    beneficiaries = [
        Beneficiary(
            retirement.account_id, "primary", spouse.name, "spouse", Decimal(100), spouse.person_id, retirement.opened
        )
    ]
    us = rng.sample(US_FUNDS, 3)
    intl = rng.choice(INTERNATIONAL_FUNDS)
    bonds = rng.sample(BOND_FUNDS, 3)
    joint_picks = [
        (us[0], amount(rng, 280000, 520000)),
        (intl, amount(rng, 90000, 220000)),
        (bonds[0], amount(rng, 160000, 340000)),
    ]
    if trap:
        # Shares bought or held from earlier grants, well before 2025: the concentration the IPS limit is about.
        joint_picks.insert(0, (employer, amount(rng, 520000, 900000)))
    scripts: list[AccountScript] = [
        account_script(joint.account_id, amount(rng, 15000, 60000), holding_rows(rng, ids, 1, joint_picks)),
        account_script(
            plan.account_id,
            amount(rng, 1500, 6000, 500),
            holding_rows(
                rng, ids, 2, [(bonds[1], amount(rng, 10000, 40000))], acquired_from=plan_opened, basis=(96, 104)
            ),
        ),
        account_script(
            retirement.account_id,
            amount(rng, 5000, 15000),
            holding_rows(
                rng,
                ids,
                3,
                [(us[1], amount(rng, 260000, 520000)), (bonds[2], amount(rng, 120000, 260000))],
                basis=(100, 100),
            ),
        ),
    ]
    if rng.random() < 0.6:
        ira = Account(
            ids.account(4),
            "traditional_ira",
            f"Traditional IRA, {spouse.name}",
            day_between(rng, date(2004, 1, 5), date(2016, 12, 30)),
        )
        accounts.append((ira, (spouse.person_id,)))
        beneficiaries.append(
            Beneficiary(
                ira.account_id, "primary", executive.name, "spouse", Decimal(100), executive.person_id, ira.opened
            )
        )
        scripts.append(
            account_script(
                ira.account_id,
                amount(rng, 3000, 9000),
                holding_rows(
                    rng,
                    ids,
                    4,
                    [(us[2], amount(rng, 120000, 280000)), (bonds[0], amount(rng, 50000, 130000))],
                    basis=(100, 100),
                ),
            )
        )

    # Releases on a fixed day of the month, a quarter apart, all in 2025; then a sale of the earliest.
    start = rng.choice((1, 2, 3))
    months = range(start, 12, 3)
    day_of_month = rng.randint(10, 20)
    vest_days = [_on_or_after(date(2025, m, day_of_month)) for m in months]
    target = amount(rng, 70000, 220000)
    units = max(Decimal(10), (target / market.price(employer, vest_days[0]) / 10).to_integral_value() * 10)
    # The sale is more than the wash-sale window from every release, so a loss on it is never washed.
    windows = [
        (j, day + WINDOW, vest_days[j + 1] - WINDOW if j + 1 < len(vest_days) else LAST_SALE)
        for j, day in enumerate(vest_days)
    ]
    released_before, first_day, last_day = rng.choice([w for w in windows if w[1] + timedelta(days=6) <= w[2]])
    sale_day = day_between(rng, first_day, last_day)
    sold = units * rng.randint(1, released_before + 1)
    activity = [Activity("rsu_vest", day, plan.account_id, security_id=employer, units=units) for day in vest_days]
    activity.append(Activity("sell", sale_day, plan.account_id, security_id=employer, units=sold))
    if rng.random() < 0.5:
        activity.append(
            Activity(
                "withdrawal",
                day_between(rng, date(2025, 2, 3), date(2025, 10, 31)),
                joint.account_id,
                amount=amount(rng, 5000, 15000),
            )
        )
    released = ZERO
    confirmations: list[CrmActivity] = []
    for k, day in enumerate(vest_days, start=1):
        price = market.price(employer, day)
        value = cents(units * price)
        released += value
        confirmations.append(
            CrmActivity(
                ids.activity(k),
                add_weekdays(day, rng.randint(1, 4)),
                RELEASE_CONFIRMATION,
                f"Release confirmation from {alias}, forwarded by {executive.name}: {fmt(units)} restricted stock "
                f"units released on {day.isoformat()} at {usd(price)} a share (a synthetic price), a release value "
                f"of {usd(value)}, included in {first}'s 2025 wages. Shares delivered to {plan.account_id}.",
                refers_to=day,
                account_id=plan.account_id,
                security_id=employer,
                units=units,
                price=price,
            )
        )
    income = [Income(executive.person_id, WAGES, alias, amount(rng, 210000, 480000) + released, 2025)]
    if rng.random() < 0.7:
        income.append(Income(spouse.person_id, WAGES, rng.choice(EMPLOYERS), amount(rng, 60000, 190000), 2025))

    family = [executive, spouse]
    account_ids = tuple(a.account_id for a, _ in accounts)
    planted = twin = None
    if trap:
        planted = PlantedSpec(spec.item_id, ITEM_TYPE, {})
    else:
        twin = TwinSpec(
            "clean",
            f"Clean. {first}'s RSU releases from {alias} land in a stock plan account during 2025 and some are sold "
            f"in {MONTHS[sale_day.month - 1]}. The custodian booked each release at its value on the day, which "
            "matches the release confirmations in the CRM, so its tax lots and realized lots carry the right basis; "
            "and the employer stock left after the sale is within the IPS concentration limit.",
        )
    hh = household(
        ids,
        f"{surname} household",
        3,
        family,
        accounts,
        [TaxUnit(ids.tax_unit(1), "married_filing_jointly", (executive.person_id, spouse.person_id))],
        [BillingGroup(ids.billing_group(1), "FS-STD", account_ids)],
        [advisory(ids, 1, family, (executive.person_id, spouse.person_id), account_ids, joint_opened)],
        configured=max(a.opened for a, _ in accounts),
        beneficiaries=tuple(beneficiaries),
        income=tuple(income),
        crm_activities=tuple(confirmations),
    )
    return HouseholdScript(
        source=f"background/{household_id}",
        household=hh,
        pair=spec.pair,
        role="trap" if trap else "twin",
        accounts=tuple(scripts),
        activity=tuple(sorted(activity, key=lambda a: a.day)),
        planted=planted,
        twin=twin,
        background=True,
    )


def _limit(spec: PairSpec, script: HouseholdScript, market: Market) -> Decimal:
    """A round IPS limit the employer stock is above and every other holding below."""
    shares = _shares(script, market)
    employer = next(a.security_id for a in script.activity if a.kind == "rsu_vest" and a.security_id)
    others = max(share for security, share in shares.items() if security != employer)
    fits = [c for c in ROUND_LIMITS if others + BELOW <= c <= shares[employer] - ABOVE]
    if not fits:
        raise PlantError(
            f"{script.household.household_id}: no round concentration limit lies between the employer stock's "
            f"{shares[employer]:.4f} and the next holding's {others:.4f}"
        )
    return spec.rng.choice(fits)


def generate_pair(spec: PairSpec, market: Market) -> tuple[HouseholdScript, HouseholdScript]:
    drawn = _draw(spec, market, spec.trap_id, trap=True)
    trap = fit_ips(drawn, market, concentration_limit=_limit(spec, drawn, market))
    twin = fit_ips(_draw(spec, market, spec.twin_id, trap=False), market)
    return trap, twin
