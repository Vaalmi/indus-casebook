"""Archetype 6 drawn: an established RMD retiree gives part of the 2025 RMD from the IRA straight to
a charity as a qualified charitable distribution and takes the rest later in the year. The trap's
custodian codes the charity payment as an ordinary distribution (the planter rewrites its records),
so only the CRM's request and acknowledgment show it was a QCD; the clean twin's custodian codes it
as a QCD."""

from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal

from casebook.generate.background.a05_first_rmd import (
    SETTLE_WEEKDAYS,
    STEP,
    UNIFORM,
    WITHHOLDING_PCTS,
    first,
    opening_balance,
    raise_cash,
    withheld,
)
from casebook.generate.background.common import (
    BOND_FUNDS,
    CHARITIES,
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
)
from casebook.generate.script import Activity, HouseholdScript, PlantedSpec, TwinSpec
from casebook.model.dates import add_weekdays
from casebook.model.household import Account, Beneficiary, BillingGroup, CrmActivity, TaxUnit
from casebook.model.money import cents, usd
from casebook.rules import load_rules
from casebook.securities.market import Market

ITEM_TYPE = "qcd_evidenced_in_crm_only"
DISTRIBUTION_YEAR = 2025
QCD_STEP = Decimal(500)


def _draw(spec: PairSpec, household_id: str, trap: bool, market: Market) -> HouseholdScript:
    rng, ids = spec.rng, Ids(household_id)
    rules = load_rules(DISTRIBUTION_YEAR)
    surname = rng.choice(SURNAMES)
    # Aged 74 to 87 in 2025: past the required beginning date and long past 70½.
    owner = person(rng, ids, 1, "primary", born_between(rng, date(1938, 1, 1), date(1951, 6, 30)), surname)
    married = rng.random() < 0.6
    if married:
        # Within seven years of the owner, so the Uniform Lifetime table applies.
        born = born_between(rng, owner.born - timedelta(days=7 * 365), owner.born + timedelta(days=7 * 365))
        other = person(rng, ids, 2, "spouse", born, surname)
    else:
        relationship = "daughter" if rng.random() < 0.5 else "son"
        other = person(rng, ids, 2, relationship, born_between(rng, date(1962, 1, 1), date(1985, 12, 31)), surname)
    o = first(owner)
    taxable_opened = day_between(rng, date(2008, 1, 2), date(2018, 12, 31))
    if married:
        taxable = Account(ids.account(1), "joint_taxable", "Joint tenants with right of survivorship", taxable_opened)
        taxable_owners: tuple[str, ...] = (owner.person_id, other.person_id)
    else:
        taxable = Account(ids.account(1), "individual_taxable", f"Individual, {owner.name}", taxable_opened)
        taxable_owners = (owner.person_id,)
    ira_opened = day_between(rng, date(1994, 1, 3), date(2010, 12, 31))
    ira = Account(ids.account(2), "traditional_ira", f"Traditional IRA, {owner.name}", ira_opened)
    # Some spouses hold a Roth IRA, which owes no RMD in the owner's lifetime.
    roth = (
        Account(
            ids.account(3),
            "roth_ira",
            f"Roth IRA, {other.name}",
            day_between(rng, date(2011, 1, 3), date(2019, 12, 31)),
        )
        if married and rng.random() < 0.4
        else None
    )

    us, us2 = rng.sample(US_FUNDS, 2)
    intl = rng.choice(INTERNATIONAL_FUNDS)
    bond = rng.choice(BOND_FUNDS)
    muni = rng.choice(MUNI_FUNDS)
    scripts = [
        account_script(
            taxable.account_id,
            amount(rng, 12000, 32000, STEP),
            holding_rows(
                rng,
                ids,
                1,
                [
                    (us, amount(rng, 120000, 260000, STEP)),
                    (us2, amount(rng, 50000, 120000, STEP)),
                    (muni, amount(rng, 90000, 210000, STEP)),
                ],
                acquired_from=taxable_opened,
            ),
        ),
        account_script(
            ira.account_id,
            amount(rng, 8000, 18000, STEP),
            holding_rows(
                rng,
                ids,
                2,
                [
                    (us, amount(rng, 150000, 320000, STEP)),
                    (bond, amount(rng, 150000, 300000, STEP)),
                    (intl, amount(rng, 40000, 110000, STEP)),
                ],
                acquired_from=ira_opened,
                basis=(100, 100),
            ),
        ),
    ]
    if roth is not None:
        scripts.append(
            account_script(
                roth.account_id,
                amount(rng, 2000, 6000, STEP),
                holding_rows(
                    rng,
                    ids,
                    3,
                    [(us2, amount(rng, 40000, 110000, STEP)), (intl, amount(rng, 15000, 45000, STEP))],
                    acquired_from=roth.opened,
                    basis=(100, 100),
                ),
            )
        )
    ira_script = scripts[1]

    # The 2025 RMD: the IRA's 31 December 2024 balance over the Uniform Lifetime factor at the
    # owner's 2025 age. The QCD pays a round part of it, the rest follows later in the year.
    factor = rules.factor(UNIFORM, DISTRIBUTION_YEAR - owner.born.year)
    rmd = cents(opening_balance(ira_script, market) / factor)
    share = Decimal(rng.randint(25, 75)) / 100
    qcd = cents(max(Decimal(2000), (rmd * share / QCD_STEP).quantize(Decimal(1), rounding=ROUND_FLOOR) * QCD_STEP))
    rest = rmd - qcd
    charity = rng.choice(CHARITIES)
    qcd_sale = day_between(rng, date(2025, 2, 3), date(2025, 10, 24))
    qcd_day = add_weekdays(qcd_sale, SETTLE_WEEKDAYS)
    rest_sale = day_between(rng, add_weekdays(qcd_day, 10), date(2025, 12, 12))
    pct = rng.choice(WITHHOLDING_PCTS)
    activity = [
        raise_cash(ira_script, qcd, qcd_sale, market),
        Activity("qcd", qcd_day, ira.account_id, amount=qcd, charity=charity),
        raise_cash(ira_script, rest, rest_sale, market),
        Activity(
            "rmd",
            add_weekdays(rest_sale, SETTLE_WEEKDAYS),
            ira.account_id,
            amount=rest,
            tax_year=DISTRIBUTION_YEAR,
            withheld=withheld(rest, pct),
        ),
        Activity(
            "withdrawal",
            day_between(rng, date(2025, 4, 1), date(2026, 4, 10)),
            taxable.account_id,
            amount=cents(amount(rng, 5000, 14000, STEP)),
        ),
    ]
    activity.sort(key=lambda a: a.day)
    request_day = qcd_sale - timedelta(days=rng.randint(3, 21))
    acknowledged = qcd_day + timedelta(days=rng.randint(7, 40))
    crm = (
        CrmActivity(
            ids.activity(1),
            request_day,
            "qcd_request",
            f"QCD request signed by {owner.name}: pay {usd(qcd)} from IRA {ira.account_id} directly to {charity}, "
            f"a public charity, as a qualified charitable distribution toward the {DISTRIBUTION_YEAR} required "
            "minimum distribution. Sent to the custodian the same day.",
        ),
        CrmActivity(
            ids.activity(2),
            acknowledged,
            "charity_acknowledgment",
            f"Acknowledgment letter from {charity}: received {usd(qcd)} from the IRA of {owner.name} on "
            f"{qcd_day.isoformat()}, paid by the custodian directly to the charity. No goods or services were "
            f"provided in return. Filed with the {DISTRIBUTION_YEAR} tax papers.",
            refers_to=qcd_day,
            account_id=ira.account_id,
            amount=qcd,
        ),
    )

    beneficiaries = [
        Beneficiary(
            ira.account_id, "primary", other.name, other.relationship, Decimal(100), other.person_id, ira_opened
        )
    ]
    if rng.random() < 0.4:
        beneficiaries.append(
            Beneficiary(
                ira.account_id,
                "contingent",
                rng.choice([c for c in CHARITIES if c != charity]),
                "charity",
                Decimal(100),
                None,
                day_between(rng, date(2015, 1, 5), date(2023, 12, 29)),
            )
        )
    if roth is not None:
        beneficiaries.append(
            Beneficiary(roth.account_id, "primary", owner.name, "spouse", Decimal(100), owner.person_id, roth.opened)
        )
    accounts = [(taxable, taxable_owners), (ira, (owner.person_id,))]
    if roth is not None:
        accounts.append((roth, (other.person_id,)))
    all_ids = tuple(a.account_id for a, _ in accounts)
    family = [owner, other]
    parties = (owner.person_id, other.person_id) if married else (owner.person_id,)
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
        6,
        family,
        accounts,
        tax_units,
        [BillingGroup(ids.billing_group(1), "FS-STD", all_ids)],
        [advisory(ids, 1, family, parties, all_ids, taxable_opened)],
        configured=taxable_opened,
        beneficiaries=tuple(beneficiaries),
        crm_activities=crm,
    )
    planted = twin = None
    if trap:
        planted = PlantedSpec(spec.item_id, ITEM_TYPE, {})
    else:
        twin = TwinSpec(
            "clean",
            f"Clean. {o}, {DISTRIBUTION_YEAR - owner.born.year} in {DISTRIBUTION_YEAR}, paid {usd(qcd)} from the IRA "
            f"straight to {charity} on {qcd_day.isoformat()} and took the rest of the {DISTRIBUTION_YEAR} RMD, "
            f"{usd(rest)}, later in the year. The custodian coded the charity payment as a qualified charitable "
            f"distribution and the CRM's signed request and acknowledgment letter agree: it is within the "
            f"{DISTRIBUTION_YEAR} limit, {o} was over 70 and a half, and the QCD and the later distribution together "
            f"meet the {DISTRIBUTION_YEAR} RMD of {usd(rmd)}.",
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
