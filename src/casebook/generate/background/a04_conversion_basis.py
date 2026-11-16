"""Archetype 4 drawn: a pre-RMD retiree converts part of a traditional IRA that carries after-tax
basis from old nondeductible contributions, so the conversion is taxed pro rata (trap), and the
same conversion with no basis on file but a CRM record of the client's belief in it (unresolved twin)."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from casebook.generate.background.common import (
    BOND_FUNDS,
    FIRST_NAMES,
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
from casebook.generate.script import Activity, HouseholdScript, PlantedSpec, TwinSpec
from casebook.model.dates import add_weekdays
from casebook.model.household import Account, Beneficiary, BillingGroup, CrmActivity, IraBasis, Person, TaxUnit
from casebook.model.money import usd
from casebook.plant.a04_conversion_basis import ITEM_TYPE
from casebook.securities.market import Market

# Born after 1952, so no distribution is due for 2025; old enough to be retired.
BORN_FROM, BORN_TO = date(1954, 1, 1), date(1960, 12, 31)


def _first(p: Person) -> str:
    return p.name.split()[0]


def _before(day: date, count: int) -> date:
    """The weekday `count` weekdays before `day`."""
    while count > 0:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            count -= 1
    return day


def _units(value: Decimal, price: Decimal, rounding: str) -> Decimal:
    return (value / price).quantize(Decimal(1), rounding=rounding)


def _draw(spec: PairSpec, market: Market, household_id: str, basis: bool) -> HouseholdScript:
    rng, ids = spec.rng, Ids(household_id)
    surname = rng.choice(SURNAMES)
    married = rng.random() < 0.4
    owner = person(rng, ids, 1, "primary", born_between(rng, BORN_FROM, BORN_TO), surname)
    family: list[Person] = [owner]
    if married:
        family.append(person(rng, ids, 2, "spouse", born_between(rng, BORN_FROM, date(1963, 12, 31)), surname))
    first = _first(owner)
    configured = day_between(rng, date(2002, 1, 7), date(2016, 12, 16))
    if married:
        taxable = Account(ids.account(1), "joint_taxable", "Joint tenants with right of survivorship", configured)
    else:
        taxable = Account(ids.account(1), "individual_taxable", f"Individual, {owner.name}", configured)
    ira = Account(
        ids.account(2),
        "traditional_ira",
        f"Traditional IRA, {owner.name}",
        day_between(rng, date(1988, 1, 4), date(2001, 12, 14)),
    )
    roth = Account(
        ids.account(3), "roth_ira", f"Roth IRA, {owner.name}", day_between(rng, date(2012, 1, 9), date(2022, 12, 16))
    )
    accounts = [
        (taxable, tuple(p.person_id for p in family)),
        (ira, (owner.person_id,)),
        (roth, (owner.person_id,)),
    ]

    us, sold, other = rng.sample(US_FUNDS, 3)
    bond = rng.choice(BOND_FUNDS)
    taxable_cash = amount(rng, 30000, 60000, step=10)
    scripts = [
        account_script(
            taxable.account_id,
            taxable_cash,
            holding_rows(
                rng,
                ids,
                1,
                [
                    (us, amount(rng, 150000, 320000, step=10)),
                    (bond, amount(rng, 80000, 180000, step=10)),
                    (other, amount(rng, 40000, 100000, step=10)),
                ],
                acquired_from=configured,
            ),
        ),
        account_script(
            ira.account_id,
            amount(rng, 3000, 9000, step=10),
            holding_rows(
                rng,
                ids,
                2,
                [
                    (sold, amount(rng, 110000, 240000, step=10)),
                    (us, amount(rng, 90000, 200000, step=10)),
                    (bond, amount(rng, 50000, 130000, step=10)),
                ],
                acquired_from=date(2005, 1, 3),
                basis=(100, 100),
            ),
        ),
        account_script(
            roth.account_id,
            amount(rng, 500, 3000, step=10),
            holding_rows(rng, ids, 3, [(us, amount(rng, 15000, 60000, step=10))], acquired_from=roth.opened),
        ),
    ]

    converted = amount(rng, 25000, 100000, step=100)
    converted_on = day_between(rng, date(2025, 9, 2), date(2025, 12, 12))
    sold_on = _before(converted_on, rng.randint(2, 4))
    bought_on = add_weekdays(converted_on, rng.randint(2, 4))
    # Sell a little more than the conversion, so the IRA keeps cash for its fees.
    raise_cash = converted + amount(rng, 1000, 3000, step=10)
    spending = amount(rng, 4000, 9000, step=500)
    activity = (
        Activity(
            "withdrawal", day_between(rng, date(2025, 3, 3), date(2025, 3, 21)), taxable.account_id, amount=spending
        ),
        Activity(
            "withdrawal", day_between(rng, date(2025, 9, 1), date(2025, 9, 19)), taxable.account_id, amount=spending
        ),
        Activity(
            "sell",
            sold_on,
            ira.account_id,
            security_id=sold,
            units=_units(raise_cash, market.price(sold, sold_on), ROUND_CEILING),
        ),
        Activity("roth_conversion", converted_on, ira.account_id, amount=converted, to_account_id=roth.account_id),
        Activity(
            "buy",
            bought_on,
            roth.account_id,
            security_id=us,
            units=_units(converted, market.price(us, bought_on), ROUND_FLOOR),
        ),
        Activity(
            "withdrawal", day_between(rng, date(2026, 3, 2), date(2026, 3, 20)), taxable.account_id, amount=spending
        ),
    )

    decade = rng.choice(("1990s", "1990s and 2000s", "early 2000s"))
    return_day = day_between(rng, date(2025, 4, 16), date(2025, 5, 16))
    planning_day = day_between(rng, date(2025, 6, 2), _before(converted_on, 10))
    plan = (
        f"Conversion planning with {first}: before RMDs begin, convert {usd(converted)} from the traditional IRA "
        f"{ira.account_id} to the Roth IRA {roth.account_id} this year, selling part of a fund in the IRA to raise "
        "the cash."
    )
    carried = amount(rng, 12000, 70000, step=10) if basis else Decimal(0)
    if basis:
        received = (
            f"{first}'s 2024 Form 1040 and Form 8606 received. The Form 8606 shows {usd(carried)} of basis in "
            f"{first}'s traditional IRAs, from nondeductible contributions made in the {decade}, carried to 2025."
        )
    else:
        received = f"{first}'s 2024 Form 1040 received. It reports no IRA basis and no Form 8606 is attached."
        plan += (
            f" {first} says nondeductible contributions went into the IRA in the {decade}, when they could not be "
            f"deducted, but no Form 8606 is on file with us or with the current preparer. {first} will look for the "
            "returns from those years."
        )
    crm = (
        CrmActivity(ids.activity(1), return_day, "document_received", received),
        CrmActivity(ids.activity(2), planning_day, "meeting", plan),
    )

    if married:
        spouse = family[1]
        heirs = [(spouse.name, "spouse", spouse.person_id, Decimal(100))]
    else:
        children = rng.sample(FIRST_NAMES, 2)
        heirs = [(f"{c} {surname}", rng.choice(("daughter", "son")), None, Decimal(50)) for c in children]
    beneficiaries = tuple(
        Beneficiary(account.account_id, "primary", name, relation, share, pid, account.opened)
        for account in (ira, roth)
        for name, relation, pid, share in heirs
    )
    filing = "married_filing_jointly" if married else "single"
    all_accounts = tuple(a.account_id for a, _ in accounts)
    hh = household(
        ids,
        f"{surname} household",
        4,
        family,
        accounts,
        [TaxUnit(ids.tax_unit(1), filing, tuple(p.person_id for p in family))],
        [BillingGroup(ids.billing_group(1), "FS-STD", all_accounts)],
        [advisory(ids, 1, family, tuple(p.person_id for p in family), all_accounts, roth.opened)],
        configured=configured,
        beneficiaries=beneficiaries,
        crm_activities=crm,
    )
    planted = twin = None
    if basis:
        profile = hh.tax_profile
        hh = replace(
            hh,
            tax_profile=replace(
                profile,
                ira_basis=tuple(
                    IraBasis(b.person_id, carried if b.person_id == owner.person_id else b.basis)
                    for b in profile.ira_basis
                ),
            ),
        )
        planted = PlantedSpec(spec.item_id, ITEM_TYPE, {"person_id": owner.person_id})
    else:
        twin = TwinSpec(
            "unresolved",
            f"Unresolved. {first} converted {usd(converted)} from the traditional IRA to the Roth IRA on "
            f"{converted_on.isoformat()}. The 2024 return carries no IRA basis, so on the records the whole conversion "
            f"is taxable. But {first} told the advisor of nondeductible contributions to the IRA in the {decade}, and "
            "no Form 8606 is on file to prove or rule out that basis. If there is basis, part of the conversion is "
            "nontaxable under the pro-rata rule of IRC § 408(d)(2); if not, all of it is taxable. The taxable part "
            "cannot be settled until the old Forms 8606 or returns are found; the right answer is to say so and ask "
            "for them, not to assume either way.",
        )
    return HouseholdScript(
        source=f"background/{household_id}",
        household=hh,
        pair=spec.pair,
        role="trap" if basis else "twin",
        accounts=tuple(scripts),
        activity=activity,
        planted=planted,
        twin=twin,
        background=True,
    )


def generate_pair(spec: PairSpec, market: Market) -> tuple[HouseholdScript, HouseholdScript]:
    trap = fit_ips(_draw(spec, market, spec.trap_id, basis=True), market)
    twin = fit_ips(_draw(spec, market, spec.twin_id, basis=False), market)
    return trap, twin
