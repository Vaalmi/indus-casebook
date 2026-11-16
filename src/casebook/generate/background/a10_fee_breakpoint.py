"""Archetype 10 drawn: a householding letter the billing ignores (trap), and the same shape with no
letter (near-miss twin). The worked example the other archetypes' generators follow."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from casebook.generate.background.common import (
    BOND_FUNDS,
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
from casebook.model.household import Account, Agreement, Beneficiary, BillingGroup, TaxUnit
from casebook.securities.market import Market

ITEM_TYPE = "missed_fee_breakpoint"


def _draw(spec: PairSpec, household_id: str, letter: bool) -> HouseholdScript:
    rng, ids = spec.rng, Ids(household_id)
    surname = spec.rng.choice(SURNAMES)
    parent = person(rng, ids, 1, "primary", born_between(rng, date(1956, 1, 1), date(1970, 12, 31)), surname)
    spouse = person(rng, ids, 2, "spouse", born_between(rng, date(1955, 1, 1), date(1971, 12, 31)), surname)
    child = person(
        rng,
        ids,
        3,
        "daughter" if rng.random() < 0.5 else "son",
        born_between(rng, date(1990, 1, 1), date(1999, 12, 31)),
        surname,
    )
    joint = Account(ids.account(1), "joint_taxable", "Joint tenants with right of survivorship", date(2014, 3, 3))
    ira = Account(ids.account(2), "traditional_ira", f"Traditional IRA, {spouse.name}", date(2011, 6, 1))
    own = Account(ids.account(3), "individual_taxable", f"Individual, {child.name}", date(2021, 9, 1))
    accounts = [(joint, (parent.person_id, spouse.person_id)), (ira, (spouse.person_id,)), (own, (child.person_id,))]
    us, intl, bond = rng.choice(US_FUNDS), rng.choice(INTERNATIONAL_FUNDS), rng.choice(BOND_FUNDS)
    scripts = [
        account_script(
            joint.account_id,
            amount(rng, 15000, 40000),
            holding_rows(
                rng,
                ids,
                1,
                [
                    (us, amount(rng, 260000, 380000)),
                    (intl, amount(rng, 90000, 150000)),
                    (bond, amount(rng, 180000, 260000)),
                ],
            ),
        ),
        account_script(
            ira.account_id,
            amount(rng, 3000, 9000),
            holding_rows(rng, ids, 2, [(bond, amount(rng, 150000, 230000)), (us, amount(rng, 150000, 220000))]),
        ),
        account_script(
            own.account_id,
            amount(rng, 10000, 25000),
            holding_rows(
                rng,
                ids,
                3,
                [(us, amount(rng, 200000, 300000)), (bond, amount(rng, 120000, 180000))],
                acquired_from=date(2021, 10, 1),
            ),
        ),
    ]
    family = [parent, spouse, child]
    signed_parents = date(2014, 3, 3)
    agreements: list[Agreement] = [
        advisory(
            ids, 1, family, (parent.person_id, spouse.person_id), (joint.account_id, ira.account_id), signed_parents
        ),
        advisory(ids, 2, family, (child.person_id,), (own.account_id,), date(2021, 9, 1)),
    ]
    planted = twin = None
    if letter:
        signed = day_between(rng, date(2023, 6, 1), date(2024, 11, 29))
        agreements.append(
            Agreement(
                ids.agreement(3),
                "householding",
                (parent.person_id, spouse.person_id, child.person_id),
                (joint.account_id, ira.account_id, own.account_id),
                signed,
                f"Householding letter: the joint account, {spouse.name.split()[0]}'s IRA and {child.name.split()[0]}'s "
                "individual account are billed together as one group from the next billing cycle.",
            )
        )
        planted = PlantedSpec(spec.item_id, ITEM_TYPE, {"agreement_id": ids.agreement(3)})
    else:
        twin = TwinSpec(
            "near_miss",
            f"A near miss. The three accounts together are worth more than $1,000,000 and are billed in two groups, "
            f"which looks like a missed breakpoint. But {child.name.split()[0]}'s account is under its own advisory "
            "agreement and no householding agreement joins it to the parents' accounts, so billing it on its own is "
            "correct.",
        )
    hh = household(
        ids,
        f"{surname} household",
        10,
        family,
        accounts,
        [
            TaxUnit(ids.tax_unit(1), "married_filing_jointly", (parent.person_id, spouse.person_id)),
            TaxUnit(ids.tax_unit(2), "single", (child.person_id,)),
        ],
        [
            BillingGroup(ids.billing_group(1), "FS-STD", (joint.account_id, ira.account_id)),
            BillingGroup(ids.billing_group(2), "FS-STD", (own.account_id,)),
        ],
        agreements,
        configured=date(2021, 9, 1),
        beneficiaries=(
            Beneficiary(ira.account_id, "primary", parent.name, "spouse", Decimal(100), parent.person_id, ira.opened),
        ),
    )
    contribution = day_between(rng, date(2025, 3, 3), date(2025, 9, 30))
    activity = (Activity("contribution", contribution, joint.account_id, amount=amount(rng, 5000, 20000)),)
    return HouseholdScript(
        source=f"background/{household_id}",
        household=hh,
        pair=spec.pair,
        role="trap" if letter else "twin",
        accounts=tuple(scripts),
        activity=activity,
        planted=planted,
        twin=twin,
        background=True,
    )


def generate_pair(spec: PairSpec, market: Market) -> tuple[HouseholdScript, HouseholdScript]:
    trap = fit_ips(_draw(spec, spec.trap_id, letter=True), market)
    twin = fit_ips(_draw(spec, spec.twin_id, letter=False), market)
    return replace(trap), replace(twin)
