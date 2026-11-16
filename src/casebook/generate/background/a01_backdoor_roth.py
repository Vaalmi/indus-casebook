"""Archetype 1 drawn: a backdoor Roth taxed pro rata because a rollover IRA holds pre-tax money at
year end (trap), and the same backdoor Roth with the pre-tax money in a former employer's 401(k),
which Form 8606 does not count (near-miss twin)."""

from datetime import date
from decimal import ROUND_FLOOR, Decimal

from casebook.generate.background.common import (
    BOND_FUNDS,
    EMPLOYERS,
    INTERNATIONAL_FUNDS,
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
from casebook.model.household import Account, Beneficiary, BillingGroup, CrmActivity, Income, Person, TaxUnit
from casebook.model.money import usd
from casebook.plant.a01_backdoor_roth import ITEM_TYPE, TAX_YEAR
from casebook.rules import load_rules
from casebook.securities.market import Market

PRE_TAX = (100, 100)  # Pre-tax money: the custodian's cost is what went in.


def _limit(born: date) -> Decimal:
    """The most the person may contribute for 2025: the limit, plus the catch-up at 50 or over."""
    rules = load_rules(TAX_YEAR)
    catch_up = rules.value("ira_catch_up") if TAX_YEAR - born.year >= 50 else Decimal(0)
    return rules.value("ira_contribution_limit") + catch_up


def _units(market: Market, security: str, day: date, spend: Decimal) -> Decimal:
    return (spend / market.price(security, day)).quantize(Decimal(1), rounding=ROUND_FLOOR)


def _draw(spec: PairSpec, market: Market, household_id: str, rollover: bool) -> HouseholdScript:
    rng, ids = spec.rng, Ids(household_id)
    surname = rng.choice(SURNAMES)
    primary = person(rng, ids, 1, "primary", born_between(rng, date(1973, 1, 1), date(1992, 12, 31)), surname)
    spouse_surname = surname if rng.random() < 0.5 else rng.choice(SURNAMES)
    spouse = person(rng, ids, 2, "spouse", born_between(rng, date(1972, 1, 1), date(1993, 12, 31)), spouse_surname)
    converter, partner = (primary, spouse) if rng.random() < 0.5 else (spouse, primary)
    first = converter.name.split()[0]
    employers = rng.sample(EMPLOYERS, 3)
    former = employers[2]

    opened_joint = day_between(rng, date(2009, 1, 5), date(2020, 12, 18))
    opened_new = day_between(rng, date(2024, 11, 4), date(2024, 12, 20))
    joint = Account(ids.account(1), "joint_taxable", "Joint tenants with right of survivorship", opened_joint)
    if rollover:
        pre_tax = Account(
            ids.account(2),
            "traditional_ira",
            f"Rollover IRA, {converter.name}",
            day_between(rng, date(2016, 1, 4), date(2023, 12, 15)),
        )
    else:
        pre_tax = Account(
            ids.account(2),
            "401k",
            f"401(k), {converter.name}, former employer plan of {former}",
            day_between(rng, date(2010, 1, 4), date(2019, 12, 16)),
        )
    new_ira = Account(ids.account(3), "traditional_ira", f"Traditional IRA, {converter.name}", opened_new)
    roth = Account(
        ids.account(4), "roth_ira", f"Roth IRA, {converter.name}", day_between(rng, date(2010, 1, 4), date(2021, 6, 30))
    )
    accounts = [
        (joint, (primary.person_id, spouse.person_id)),
        (pre_tax, (converter.person_id,)),
        (new_ira, (converter.person_id,)),
        (roth, (converter.person_id,)),
    ]

    us, roth_fund = rng.sample(US_FUNDS, 2)
    intl, bond = rng.choice(INTERNATIONAL_FUNDS), rng.choice(BOND_FUNDS)
    scripts = [
        account_script(
            joint.account_id,
            amount(rng, 12000, 40000, step=10),
            holding_rows(
                rng,
                ids,
                1,
                [
                    (us, amount(rng, 120000, 260000, step=10)),
                    (intl, amount(rng, 30000, 90000, step=10)),
                    (bond, amount(rng, 40000, 110000, step=10)),
                ],
                acquired_from=opened_joint,
            ),
        ),
        account_script(
            pre_tax.account_id,
            amount(rng, 1000, 5000, step=10),
            holding_rows(
                rng,
                ids,
                2,
                [(us, amount(rng, 60000, 200000, step=10)), (bond, amount(rng, 25000, 80000, step=10))],
                acquired_from=pre_tax.opened,
                basis=PRE_TAX,
            ),
        ),
        account_script(new_ira.account_id, Decimal(0), []),
        account_script(
            roth.account_id,
            amount(rng, 300, 2500, step=10),
            holding_rows(rng, ids, 4, [(roth_fund, amount(rng, 9000, 45000, step=10))], acquired_from=roth.opened),
        ),
    ]

    limit = _limit(converter.born)
    # Contribute and convert inside the first quarter, so the new IRA is empty at its first billing.
    contributed = day_between(rng, date(2025, 1, 6), date(2025, 3, 7))
    converted = add_weekdays(contributed, rng.randint(2, 7))
    bought = add_weekdays(converted, rng.randint(2, 5))
    added = day_between(rng, date(2025, 4, 7), date(2025, 10, 31))
    added_amount = amount(rng, 10000, 40000, step=500)
    added_bought = add_weekdays(added, 2)
    activity = (
        Activity("contribution", contributed, new_ira.account_id, amount=limit),
        Activity("roth_conversion", converted, new_ira.account_id, amount=limit, to_account_id=roth.account_id),
        Activity("buy", bought, roth.account_id, security_id=roth_fund, units=_units(market, roth_fund, bought, limit)),
        Activity("contribution", added, joint.account_id, amount=added_amount),
        Activity(
            "buy",
            added_bought,
            joint.account_id,
            security_id=us,
            units=_units(market, us, added_bought, added_amount),
        ),
    )

    wages = [amount(rng, 130000, 240000, step=500), amount(rng, 130000, 240000, step=500)]
    payers = employers[:2]
    family: list[Person] = [primary, spouse]
    income = tuple(
        Income(p.person_id, "wages", payer, w, TAX_YEAR) for p, payer, w in zip(family, payers, wages, strict=True)
    )
    where = (
        f"The rollover IRA {pre_tax.account_id} from a former employer stays as it is."
        if rollover
        else f"{first}'s pre-tax savings stay in the former employer's 401(k) {pre_tax.account_id}."
    )
    w2_day = day_between(rng, date(2026, 1, 26), date(2026, 2, 27))
    crm = (
        CrmActivity(
            ids.activity(1),
            opened_new,
            "meeting",
            f"Planning meeting with {primary.name.split()[0]} and {spouse.name.split()[0]}. Their wages are above "
            f"the Roth IRA income limit, so {first} will make a 2025 IRA contribution to the new traditional IRA "
            f"{new_ira.account_id}, nondeductible, and convert it to the Roth IRA {roth.account_id}. {where}",
        ),
        CrmActivity(
            ids.activity(2),
            w2_day,
            "document_received",
            "2025 Forms W-2 received: "
            + "; ".join(
                f"{p.name.split()[0]}, {payer}, wages {usd(w)}"
                for p, payer, w in zip(family, payers, wages, strict=True)
            )
            + ".",
        ),
    )
    beneficiaries = tuple(
        Beneficiary(a.account_id, "primary", partner.name, "spouse", Decimal(100), partner.person_id, a.opened)
        for a in (pre_tax, new_ira, roth)
    )

    planted = twin = None
    if rollover:
        planted = PlantedSpec(spec.item_id, ITEM_TYPE, {"person_id": converter.person_id})
    else:
        days = (converted - contributed).days
        twin = TwinSpec(
            "near_miss",
            f"A near miss. {first} made a backdoor Roth: a {usd(limit)} nondeductible contribution to a new "
            f"traditional IRA, converted to the Roth IRA {days} days later. That looks like the pro-rata trap, because "
            f"{first} has a large pre-tax balance. But it sits in a former employer's 401(k), and Form 8606 line 6 "
            f"counts only traditional, SEP and SIMPLE IRAs. {first}'s only traditional IRA was empty on 31 December "
            f"2025, so line 10 is 1.000, the whole {usd(limit)} conversion is nontaxable, and no basis carries to "
            "2026.",
        )
    all_accounts = tuple(a.account_id for a, _ in accounts)
    hh = household(
        ids,
        f"{surname} household" if spouse_surname == surname else f"{surname}-{spouse_surname} household",
        1,
        family,
        accounts,
        [TaxUnit(ids.tax_unit(1), "married_filing_jointly", (primary.person_id, spouse.person_id))],
        [BillingGroup(ids.billing_group(1), "FS-STD", all_accounts)],
        [advisory(ids, 1, family, (primary.person_id, spouse.person_id), all_accounts, opened_new)],
        configured=opened_joint,
        beneficiaries=beneficiaries,
        income=income,
        crm_activities=crm,
    )
    return HouseholdScript(
        source=f"background/{household_id}",
        household=hh,
        pair=spec.pair,
        role="trap" if rollover else "twin",
        accounts=tuple(scripts),
        activity=activity,
        planted=planted,
        twin=twin,
        background=True,
    )


def generate_pair(spec: PairSpec, market: Market) -> tuple[HouseholdScript, HouseholdScript]:
    trap = fit_ips(_draw(spec, market, spec.trap_id, rollover=True), market)
    twin = fit_ips(_draw(spec, market, spec.twin_id, rollover=False), market)
    return trap, twin
