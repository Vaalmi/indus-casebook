"""Archetype 7 drawn: an adult child inherited a parent's traditional IRA after 2020 and took nothing
from it in 2025. In the trap the parent died on or after the required beginning date, so the ten-year
rule brings an annual RMD with it; in the near-miss twin the parent died before it, so only the
ten-year deadline applies.

These background pairs are public: only archetype 7's featured pair is held out."""

from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal

from casebook.generate.background.a05_first_rmd import STEP, first
from casebook.generate.background.common import (
    BOND_FUNDS,
    FIRST_NAMES,
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
from casebook.model.household import Account, Agreement, Beneficiary, BillingGroup, CrmActivity, Decedent, TaxUnit
from casebook.model.money import cents
from casebook.plant.a05_first_rmd import required_beginning_date
from casebook.rules import load_rules
from casebook.securities.market import Market

ITEM_TYPE = "inherited_ira_annual_rmd"
DISTRIBUTION_YEAR = 2025
# Deaths from 2021 (the ten-year rule covers deaths after 2019, and 2020's RMDs were waived) to the
# summer of 2024, so the inherited IRA is open before the 31 December 2024 balance.
FIRST_DEATH, LAST_DEATH = date(2021, 1, 4), date(2024, 7, 31)


def _years(day: date, years: int) -> date:
    return day.replace(year=day.year + years, day=min(day.day, 28))


def _age(born: date, on: date) -> int:
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def _draw(spec: PairSpec, household_id: str, trap: bool, market: Market) -> HouseholdScript:
    rng, ids = spec.rng, Ids(household_id)
    rules = load_rules(DISTRIBUTION_YEAR)
    surname = rng.choice(SURNAMES)
    if trap:
        # Born before 1 July 1949, so the required beginning date fell before the death.
        parent_born = born_between(rng, date(1931, 1, 1), date(1949, 6, 30))
        rbd = required_beginning_date(rules, parent_born)
        died = born_between(rng, max(FIRST_DEATH, rbd), LAST_DEATH)
    else:
        # Born 1951 to 1959: reaching the applicable age after the death.
        parent_born = born_between(rng, date(1951, 1, 1), date(1959, 12, 31))
        rbd = required_beginning_date(rules, parent_born)
        died = born_between(rng, FIRST_DEATH, min(LAST_DEATH, rbd - timedelta(days=1)))
    # A child at least twenty years younger, an adult at the death, and born after 1957, so no
    # traditional IRA of theirs owes an RMD of its own.
    heir_born = born_between(
        rng, max(_years(parent_born, 20), date(1958, 1, 1)), min(_years(parent_born, 40), date(1994, 12, 31))
    )
    heir = person(rng, ids, 1, "primary", heir_born, surname)
    parent_surname = surname if rng.random() < 0.7 else rng.choice(SURNAMES)
    parent_name = f"{rng.choice(FIRST_NAMES)} {parent_surname}"
    parent_is = "mother" if rng.random() < 0.5 else "father"
    decedent = Decedent(parent_name, parent_born, died)
    married = rng.random() < 0.65
    family = [heir]
    if married:
        spouse_born = born_between(
            rng, max(heir_born - timedelta(days=6 * 365), date(1958, 1, 1)), heir_born + timedelta(days=6 * 365)
        )
        family.append(person(rng, ids, 2, "spouse", spouse_born, surname))
    h = first(heir)

    taxable_opened = day_between(rng, date(2010, 1, 4), date(2020, 12, 31))
    if married:
        taxable = Account(ids.account(1), "joint_taxable", "Joint tenants with right of survivorship", taxable_opened)
        taxable_owners: tuple[str, ...] = (heir.person_id, family[1].person_id)
    else:
        taxable = Account(ids.account(1), "individual_taxable", f"Individual, {heir.name}", taxable_opened)
        taxable_owners = (heir.person_id,)
    claimed = died + timedelta(days=rng.randint(30, 75))
    opened = add_weekdays(claimed, rng.randint(3, 20))
    inherited = Account(
        ids.account(2),
        "inherited_ira",
        f"Inherited IRA, {parent_name}, deceased {died.isoformat()}, FBO {heir.name}",
        opened,
        decedent,
    )
    own_ira = (
        Account(
            ids.account(3),
            "traditional_ira",
            f"Traditional IRA, {heir.name}",
            day_between(rng, date(2005, 1, 3), date(2019, 12, 31)),
        )
        if rng.random() < 0.4
        else None
    )

    us, us2 = rng.sample(US_FUNDS, 2)
    intl, intl2 = rng.sample(INTERNATIONAL_FUNDS, 2)
    bond = rng.choice(BOND_FUNDS)
    scripts = [
        account_script(
            taxable.account_id,
            amount(rng, 9000, 30000, STEP),
            holding_rows(
                rng,
                ids,
                1,
                [
                    (us, amount(rng, 120000, 300000, STEP)),
                    (intl, amount(rng, 40000, 110000, STEP)),
                    (bond, amount(rng, 50000, 140000, STEP)),
                ],
                acquired_from=taxable_opened,
            ),
        ),
        account_script(
            inherited.account_id,
            amount(rng, 4000, 12000, STEP),
            holding_rows(
                rng,
                ids,
                2,
                [
                    (us2, amount(rng, 110000, 260000, STEP)),
                    (bond, amount(rng, 90000, 200000, STEP)),
                    (intl2, amount(rng, 25000, 70000, STEP)),
                ],
                acquired_from=add_weekdays(opened, 1),
                acquired_to=add_weekdays(opened, 10),
                basis=(100, 100),
            ),
        ),
    ]
    if own_ira is not None:
        scripts.append(
            account_script(
                own_ira.account_id,
                amount(rng, 2000, 8000, STEP),
                holding_rows(
                    rng,
                    ids,
                    3,
                    [(us, amount(rng, 40000, 140000, STEP)), (bond, amount(rng, 20000, 70000, STEP))],
                    acquired_from=own_ira.opened,
                    basis=(100, 100),
                ),
            )
        )

    # 2025: a rebalance inside the inherited IRA, but nothing taken from it.
    sold = day_between(rng, date(2025, 3, 3), date(2025, 10, 31))
    bought = add_weekdays(sold, 2)
    bond_units = (scripts[1].holdings[1].value / market.price(bond, sold) / 5).quantize(
        Decimal(1), rounding=ROUND_FLOOR
    )
    proceeds = bond_units * market.price(bond, sold)
    added = day_between(rng, date(2025, 2, 3), date(2025, 6, 27))
    top_up = cents(amount(rng, 6000, 18000, STEP))
    activity = [
        Activity("sell", sold, inherited.account_id, security_id=bond, units=bond_units),
        Activity(
            "buy",
            bought,
            inherited.account_id,
            security_id=intl2,
            units=(proceeds * Decimal("0.95") / market.price(intl2, bought)).quantize(Decimal(1), rounding=ROUND_FLOOR),
        ),
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
            day_between(rng, date(2025, 11, 3), date(2026, 4, 10)),
            taxable.account_id,
            amount=cents(amount(rng, 5000, 12000, STEP)),
        ),
    ]
    activity.sort(key=lambda a: a.day)

    if trap:
        confirmation = (
            f"The prior custodian confirms that {parent_name} had taken required minimum distributions since "
            f"{rbd.year - 1} and that the {died.year} distribution was paid in full before the death."
        )
    else:
        confirmation = (
            f"The prior custodian confirms that {parent_name} had not begun required minimum distributions from "
            "the traditional IRA."
        )
    relation = "son" if rng.random() < 0.5 else "daughter"
    crm = (
        CrmActivity(
            ids.activity(1),
            died + timedelta(days=rng.randint(10, 28)),
            "death_certificate",
            f"Certified death certificate received for {parent_name}, {h}'s {parent_is}: born "
            f"{parent_born.isoformat()}, died {died.isoformat()}.",
        ),
        CrmActivity(
            ids.activity(2),
            claimed,
            "beneficiary_claim",
            f"Beneficiary claim signed by {heir.name}, {relation} and sole primary beneficiary of {parent_name}'s "
            "traditional IRA, electing an inherited IRA in their own name.",
        ),
        CrmActivity(ids.activity(3), claimed, "custodian_confirmation", confirmation),
    )

    accounts = [(taxable, taxable_owners), (inherited, (heir.person_id,))]
    beneficiaries: list[Beneficiary] = []
    if married:
        beneficiaries.append(
            Beneficiary(
                inherited.account_id, "primary", family[1].name, "spouse", Decimal(100), family[1].person_id, opened
            )
        )
    if own_ira is not None:
        accounts.append((own_ira, (heir.person_id,)))
        who = family[1] if married else None
        beneficiaries.append(
            Beneficiary(
                own_ira.account_id,
                "primary",
                who.name if who else f"{rng.choice(FIRST_NAMES)} {surname}",
                "spouse" if who else "sibling",
                Decimal(100),
                who.person_id if who else None,
                own_ira.opened,
            )
        )
    own_ids = tuple(a.account_id for a, _ in accounts if a.account_id != taxable.account_id)
    agreements = [
        advisory(ids, 1, family, taxable_owners, (taxable.account_id,), taxable_opened),
        Agreement(
            ids.agreement(2),
            "advisory",
            (heir.person_id,),
            own_ids,
            opened,
            f"Advisory agreement for {h}'s inherited IRA from {parent_name}"
            + (" and own traditional IRA" if own_ira is not None else "")
            + " on the standard fee schedule, billed with the taxable account.",
        ),
    ]
    tax_units = (
        [TaxUnit(ids.tax_unit(1), "married_filing_jointly", taxable_owners)]
        if married
        else [TaxUnit(ids.tax_unit(1), "single", (heir.person_id,))]
    )
    hh = household(
        ids,
        f"{surname} household",
        7,
        family,
        accounts,
        tax_units,
        [BillingGroup(ids.billing_group(1), "FS-STD", tuple(a.account_id for a, _ in accounts))],
        agreements,
        configured=taxable_opened,
        beneficiaries=tuple(beneficiaries),
        crm_activities=crm,
    )
    planted = twin = None
    if trap:
        planted = PlantedSpec(spec.item_id, ITEM_TYPE, {})
    else:
        final = died.year + int(rules.value("inherited_ira_years"))
        twin = TwinSpec(
            "near_miss",
            f"A near miss. {h} inherited the traditional IRA of {parent_name}, {h}'s {parent_is}, who died on "
            f"{died.isoformat()}, and took nothing from it in {DISTRIBUTION_YEAR}, which looks like a missed annual "
            f"RMD. But {parent_name} died at {_age(parent_born, died)}, "
            f"before the required beginning date of {rbd.isoformat()}, so the ten-year rule applies without annual "
            f"distributions: {h} need only empty the account by 31 December {final}.",
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
    return trap, twin
