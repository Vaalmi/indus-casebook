"""Archetype 8 drawn: a spouse dies holding a joint account with right of survivorship; the custodian
never books the step-up and the survivor's IRA still names the dead spouse (trap), or the custodian
books it and the survivor has named new beneficiaries (clean twin)."""

from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal

from casebook.generate.background.common import (
    BOND_FUNDS,
    FIRST_NAMES,
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
    with_social_security,
)
from casebook.generate.script import AccountScript, Activity, HouseholdScript, PlantedSpec, TwinSpec
from casebook.model.dates import PRIOR_YEAR_END, SCENARIO_DATE, add_weekdays
from casebook.model.household import Account, Beneficiary, BillingGroup, CrmActivity, TaxUnit
from casebook.model.money import cents
from casebook.plant.a08_widowed import (
    CUSTODIAN_REQUEST,
    DEATH_NOTIFICATION,
    ITEM_TYPE,
    QUALIFIED_JOINT_SHARE,
    SURVIVORSHIP,
)
from casebook.rules import load_rules
from casebook.securities.market import Market

# How the children share an IRA they are named on; each split sums to 100.
SPLITS = ((100,), (50, 50), (60, 40), (34, 33, 33))
RMD_BORN_BY = date(1952, 12, 31)
WITHHOLDING = Decimal("0.10")
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


def _opening_value(account: AccountScript, market: Market) -> Decimal:
    """The account's 31 December 2024 balance: each holding's whole units at that day's price, plus cash."""
    total = account.cash
    for holding in account.holdings:
        price = market.price(holding.security_id, PRIOR_YEAR_END)
        total += cents((holding.value / price).quantize(Decimal(1), rounding=ROUND_FLOOR) * price)
    return total


def _draw(spec: PairSpec, market: Market, household_id: str, stale: bool) -> HouseholdScript:
    rng, ids = spec.rng, Ids(household_id)
    surname = rng.choice(SURNAMES)
    survivor_born = born_between(rng, date(1946, 1, 1), date(1962, 12, 31))
    # Within ten years either way, so the survivor's 2025 distribution, if one is due, uses the Uniform table.
    decedent_born = born_between(
        rng, survivor_born - timedelta(days=8 * 365), min(survivor_born + timedelta(days=6 * 365), date(1962, 12, 31))
    )
    died = day_between(rng, date(2025, 2, 3), date(2025, 9, 30))
    survivor_is_primary = rng.random() < 0.5
    survivor = person(
        rng,
        ids,
        1 if survivor_is_primary else 2,
        "primary" if survivor_is_primary else "spouse",
        survivor_born,
        surname,
    )
    decedent = survivor
    while decedent.name == survivor.name:
        decedent = person(
            rng,
            ids,
            2 if survivor_is_primary else 1,
            "spouse" if survivor_is_primary else "primary",
            decedent_born,
            surname,
            died=died,
        )
    family = sorted([survivor, decedent], key=lambda p: p.person_id)
    s_first, d_first = survivor.name.split()[0], decedent.name.split()[0]

    opened = day_between(rng, date(1994, 1, 3), date(2010, 12, 31))
    joint = Account(ids.account(1), "joint_taxable", SURVIVORSHIP, opened)
    ira = Account(
        ids.account(2),
        "traditional_ira",
        f"Traditional IRA, {survivor.name}",
        day_between(rng, date(1996, 1, 2), date(2012, 12, 31)),
    )
    accounts = [(joint, (family[0].person_id, family[1].person_id)), (ira, (survivor.person_id,))]
    us = rng.sample(US_FUNDS, 2)
    bonds = rng.sample(BOND_FUNDS, 2)
    picks = [
        (us[0], amount(rng, 240000, 420000)),
        (rng.choice(STOCKS), amount(rng, 90000, 220000)),
        (bonds[0], amount(rng, 150000, 300000)),
    ]
    if rng.random() < 0.5:
        picks.insert(1, (rng.choice([s for s in US_FUNDS if s not in us]), amount(rng, 120000, 280000)))
    joint_rows = holding_rows(
        rng, ids, 1, picks, acquired_from=date(2000, 1, 3), acquired_to=date(2019, 12, 31), basis=(25, 75)
    )
    # The bond fund was bought later, near its value.
    joint_rows[-1].update(basis_pct=Decimal(rng.randint(95, 106)))
    rmd_due = survivor_born <= RMD_BORN_BY
    scripts = [
        account_script(joint.account_id, amount(rng, 25000, 60000), joint_rows),
        account_script(
            ira.account_id,
            amount(rng, 25000, 45000) if rmd_due else amount(rng, 4000, 12000),
            holding_rows(
                rng,
                ids,
                2,
                [(bonds[1], amount(rng, 160000, 300000)), (us[1], amount(rng, 110000, 220000))],
                basis=(100, 100),
            ),
        ),
    ]
    roth = None
    if rng.random() < 0.3:
        roth = Account(
            ids.account(3),
            "roth_ira",
            f"Roth IRA, {survivor.name}",
            day_between(rng, date(2008, 1, 2), date(2018, 12, 31)),
        )
        accounts.append((roth, (survivor.person_id,)))
        scripts.append(
            account_script(
                roth.account_id,
                amount(rng, 2000, 8000),
                holding_rows(rng, ids, 3, [(us[1], amount(rng, 60000, 150000))], basis=(100, 100)),
            )
        )
    survivor_iras = [a for a in (ira, roth) if a is not None]

    activity = [
        Activity("death", died, joint.account_id, person_id=decedent.person_id, share=QUALIFIED_JOINT_SHARE),
        Activity(
            "withdrawal",
            day_between(rng, date(2025, 1, 13), died - timedelta(days=7)),
            joint.account_id,
            amount=amount(rng, 5000, 10000),
        ),
        Activity(
            "withdrawal",
            day_between(rng, died + timedelta(days=14), date(2025, 12, 15)),
            joint.account_id,
            amount=amount(rng, 8000, 16000),
        ),
    ]
    if rmd_due:
        # The survivor's own 2025 distribution: the 31 December 2024 balance over the Uniform Lifetime factor.
        factor = load_rules().factor("uniform_lifetime", 2025 - survivor_born.year)
        due = cents(_opening_value(scripts[1], market) / factor)
        activity.append(
            Activity(
                "rmd",
                day_between(rng, date(2025, 3, 3), date(2025, 12, 15)),
                ira.account_id,
                amount=due,
                tax_year=2025,
                withheld=cents(due * WITHHOLDING),
            )
        )

    children = rng.sample([n for n in FIRST_NAMES if n not in (s_first, d_first)], rng.choice((1, 2, 2, 3)))
    split = next(s for s in SPLITS if len(s) == len(children))
    relations = [rng.choice(("son", "daughter")) for _ in children]
    notified = add_weekdays(died, rng.randint(1, 3))
    requested = add_weekdays(notified, rng.randint(1, 5))
    records = [
        CrmActivity(
            ids.activity(1),
            notified,
            DEATH_NOTIFICATION,
            f"{survivor.name} called to tell us that {decedent.name} died on {died.isoformat()}. A certified copy of "
            "the death certificate is on file.",
            refers_to=died,
            person_id=decedent.person_id,
        ),
        CrmActivity(
            ids.activity(2),
            requested,
            CUSTODIAN_REQUEST,
            f"Sent the custodian the death certificate for {decedent.name} and asked for date-of-death values on "
            f"joint account {joint.account_id}, and for the basis of {d_first}'s half of each lot to be stepped up "
            f"to its value on {died.isoformat()}.",
        ),
    ]
    beneficiaries: list[Beneficiary] = []
    iras_text = " and ".join(a.account_id for a in survivor_iras)
    named = " and ".join(f"{c} {surname}" for c in children)
    planted = twin = None
    if stale:
        for account in survivor_iras:
            beneficiaries.append(
                Beneficiary(
                    account.account_id,
                    "primary",
                    decedent.name,
                    "spouse",
                    Decimal(100),
                    decedent.person_id,
                    account.opened,
                )
            )
            beneficiaries += [
                Beneficiary(account.account_id, "contingent", f"{c} {surname}", r, Decimal(s), None, account.opened)
                for c, r, s in zip(children, relations, split, strict=True)
            ]
        if rng.random() < 0.5:
            records.append(
                CrmActivity(
                    ids.activity(3),
                    add_weekdays(requested, rng.randint(5, 20)),
                    "beneficiary_form_sent",
                    f"Sent {survivor.name} a beneficiary change form for {iras_text}, which still names "
                    f"{decedent.name} as primary beneficiary. Not yet returned.",
                )
            )
        planted = PlantedSpec(spec.item_id, ITEM_TYPE, {})
    else:
        designated = day_between(rng, requested + timedelta(days=14), min(died + timedelta(days=150), SCENARIO_DATE))
        for account in survivor_iras:
            beneficiaries += [
                Beneficiary(account.account_id, "primary", f"{c} {surname}", r, Decimal(s), None, designated)
                for c, r, s in zip(children, relations, split, strict=True)
            ]
        records.append(
            CrmActivity(
                ids.activity(3),
                designated,
                "beneficiary_form_received",
                f"Received {survivor.name}'s signed beneficiary change for {iras_text}: {named} as primary "
                f"beneficiaries in place of {decedent.name}. The custodian confirmed it the same day.",
            )
        )
        twin = TwinSpec(
            "clean",
            f"Clean. {d_first} dies in {MONTHS[died.month - 1]} 2025 and half of each lot in the couple's joint "
            "account steps up to its value on the day. Here the custodian booked the step-up, so its tax lots carry "
            f"the right basis, and {s_first} has named {named} as beneficiaries of {iras_text} in {d_first}'s place.",
        )

    account_ids = tuple(a.account_id for a, _ in accounts)
    hh = household(
        ids,
        f"{surname} household",
        8,
        family,
        accounts,
        [TaxUnit(ids.tax_unit(1), "married_filing_jointly", (family[0].person_id, family[1].person_id))],
        [BillingGroup(ids.billing_group(1), "FS-STD", account_ids)],
        [advisory(ids, 1, family, (family[0].person_id, family[1].person_id), account_ids, opened)],
        configured=opened,
        beneficiaries=tuple(beneficiaries),
        crm_activities=tuple(records),
    )
    return HouseholdScript(
        source=f"background/{household_id}",
        household=hh,
        pair=spec.pair,
        role="trap" if stale else "twin",
        accounts=tuple(scripts),
        activity=tuple(sorted(activity, key=lambda a: a.day)),
        planted=planted,
        twin=twin,
        background=True,
    )


def generate_pair(spec: PairSpec, market: Market) -> tuple[HouseholdScript, HouseholdScript]:
    trap = fit_ips(_draw(spec, market, spec.trap_id, stale=True), market)
    twin = fit_ips(_draw(spec, market, spec.twin_id, stale=False), market)
    return with_social_security(spec.rng, trap), with_social_security(spec.rng, twin)
