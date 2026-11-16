"""Archetype 9 drawn: a fund sold at a loss in the joint account and bought back in a spouse's IRA
inside the wash-sale window (trap), and the same harvest with the IRA buying on the 31st day or
later (near-miss twin)."""

from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

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
from casebook.model.dates import PRIOR_YEAR_END
from casebook.model.household import Account, Beneficiary, BillingGroup, Person, TaxUnit
from casebook.plant import PlantError
from casebook.plant.a09_wash_sale import ITEM_TYPE
from casebook.rules import load_rules
from casebook.securities.market import Market
from casebook.securities.master import by_id, load_master

HARVESTED = (*US_FUNDS, *INTERNATIONAL_FUNDS)
# The opening lot's basis is this many points above the fund's value at the sale, so the sale is a loss.
LOSS_POINTS = (6, 22)
# A basis above this share of the 31 December 2024 value is not a plausible purchase near a top.
HIGHEST_BASIS = 145
CHILD_NAMES = ("Ada", "Bram", "Cleo", "Dario", "Edda", "Futhi", "Ilan", "Juno", "Kasimir", "Lior", "Maren", "Niamh")


def _window() -> int:
    return int(load_rules().value("wash_sale_days"))


def _units(value: Decimal, price: Decimal) -> Decimal:
    return (value / price).quantize(Decimal(1), rounding=ROUND_FLOOR)


def _draw(spec: PairSpec, market: Market, household_id: str, washed: bool) -> HouseholdScript:
    rng, ids = spec.rng, Ids(household_id)
    surname = rng.choice(SURNAMES)
    primary = person(rng, ids, 1, "primary", born_between(rng, date(1957, 1, 1), date(1976, 12, 31)), surname)
    spouse_born = born_between(rng, date(1956, 1, 1), date(1978, 12, 31))
    spouse = person(rng, ids, 2, "spouse", spouse_born, surname)
    while spouse.name == primary.name:
        spouse = person(rng, ids, 2, "spouse", spouse_born, surname)
    family = [primary, spouse]
    opened = day_between(rng, date(2003, 1, 6), date(2016, 12, 30))
    joint = Account(ids.account(1), "joint_taxable", "Joint tenants with right of survivorship", opened)

    def ira(k: int, owner: Person, kind: str) -> Account:
        label = "Traditional IRA" if kind == "traditional_ira" else "Roth IRA"
        return Account(ids.account(k), kind, f"{label}, {owner.name}", day_between(rng, date(1998, 1, 5), opened))

    buyer = rng.choice(family)
    other = spouse if buyer is primary else primary
    buyer_ira = ira(2, buyer, "traditional_ira" if rng.random() < 0.7 else "roth_ira")
    other_ira = ira(3, other, "traditional_ira")
    accounts = [
        (joint, (primary.person_id, spouse.person_id)),
        (buyer_ira, (buyer.person_id,)),
        (other_ira, (other.person_id,)),
    ]

    # The harvest: a fund that has fallen most from its 31 December value, from a few drawn, sold at a loss.
    sale_day = day_between(rng, date(2025, 8, 1), date(2025, 12, 5))
    candidates = rng.sample(HARVESTED, 4)
    harvested = min(candidates, key=lambda s: (market.price(s, sale_day) / market.price(s, PRIOR_YEAR_END), s))
    ratio = market.price(harvested, sale_day) / market.price(harvested, PRIOR_YEAR_END)
    basis_pct = int((ratio * 100).to_integral_value(ROUND_CEILING)) + rng.randint(*LOSS_POINTS)
    if basis_pct > HIGHEST_BASIS:
        raise PlantError(f"{household_id}: {harvested} would need a basis of {basis_pct}% to sell at a loss")
    others = [s for s in US_FUNDS if s != harvested]
    core, swap, ira_equity = rng.sample(others, 3)
    intl = rng.choice([s for s in INTERNATIONAL_FUNDS if s != harvested])
    bond, ira_bond = rng.sample(BOND_FUNDS, 2)

    harvest_value = amount(rng, 140000, 320000)
    joint_rows = holding_rows(
        rng,
        ids,
        1,
        [
            (harvested, harvest_value),
            (core, amount(rng, 300000, 520000)),
            (bond, amount(rng, 160000, 300000)),
            (intl, amount(rng, 80000, 160000)),
        ],
    )
    # Bought near a top, so the sale is at a loss.
    joint_rows[0].update(acquired=day_between(rng, date(2021, 6, 1), date(2024, 3, 29)), basis_pct=Decimal(basis_pct))
    buyer_cash = amount(rng, 90000, 200000)
    scripts = [
        account_script(joint.account_id, amount(rng, 40000, 90000), joint_rows),
        account_script(
            buyer_ira.account_id,
            buyer_cash,
            holding_rows(
                rng,
                ids,
                2,
                [(ira_bond, amount(rng, 120000, 220000)), (ira_equity, amount(rng, 100000, 200000))],
                basis=(100, 100),
            ),
        ),
        account_script(
            other_ira.account_id,
            amount(rng, 4000, 12000),
            holding_rows(
                rng,
                ids,
                3,
                [(rng.choice(others), amount(rng, 180000, 300000)), (bond, amount(rng, 60000, 120000))],
                basis=(100, 100),
            ),
        ),
    ]

    held = _units(harvest_value, market.price(harvested, PRIOR_YEAR_END))
    sold = held if rng.random() < 0.4 else (held * Decimal(rng.randint(50, 90)) / 100).to_integral_value(ROUND_FLOOR)
    proceeds = sold * market.price(harvested, sale_day)
    swap_units = _units(proceeds * Decimal("0.95"), market.price(swap, sale_day))
    window = _window()
    if washed:
        inside = timedelta(days=window)
        if rng.random() < 0.25:
            bought_on = day_between(rng, sale_day - inside, sale_day - timedelta(days=1))
        else:
            bought_on = day_between(rng, sale_day + timedelta(days=1), sale_day + inside)
    else:
        bought_on = day_between(rng, sale_day + timedelta(days=window + 1), sale_day + timedelta(days=window + 12))
    # The IRA spends at most four fifths of its cash; the units it buys are a round number.
    affordable = _units(buyer_cash * Decimal("0.8"), market.price(harvested, bought_on))
    wanted = (sold * Decimal(rng.randint(35, 110)) / 100 / 10).to_integral_value(ROUND_FLOOR) * 10
    bought = min(wanted, affordable // 10 * 10)
    if bought <= 0:
        raise PlantError(f"{household_id}: {buyer_ira.account_id} cannot afford a unit of {harvested}")
    activity = [
        Activity("sell", sale_day, joint.account_id, security_id=harvested, units=sold),
        Activity("buy", sale_day, joint.account_id, security_id=swap, units=swap_units),
        Activity("buy", bought_on, buyer_ira.account_id, security_id=harvested, units=bought),
    ]
    if rng.random() < 0.6:
        activity.append(
            Activity(
                "withdrawal",
                day_between(rng, date(2025, 2, 3), date(2025, 7, 31)),
                joint.account_id,
                amount=amount(rng, 6000, 18000),
            )
        )

    child = f"{rng.choice(CHILD_NAMES)} {surname}"
    relation = rng.choice(("son", "daughter"))
    beneficiaries: list[Beneficiary] = []
    for account, survivor in ((buyer_ira, other), (other_ira, buyer)):
        beneficiaries += [
            Beneficiary(
                account.account_id, "primary", survivor.name, "spouse", Decimal(100), survivor.person_id, account.opened
            ),
            Beneficiary(account.account_id, "contingent", child, relation, Decimal(100), None, account.opened),
        ]

    account_ids = tuple(a.account_id for a, _ in accounts)
    planted = twin = None
    if washed:
        planted = PlantedSpec(spec.item_id, ITEM_TYPE, {})
    else:
        fund = by_id(load_master())[harvested].alias
        twin = TwinSpec(
            "near_miss",
            f"A near miss. The couple sell the {fund} at a loss in their joint account and "
            f"{buyer.name.split()[0]}'s IRA buys the same fund back. Here the IRA buys it "
            f"{(bought_on - sale_day).days} days after the sale, outside the {window} days after it that IRC § 1091 "
            "counts, so it is not a wash sale and the whole loss is allowed.",
        )
    hh = household(
        ids,
        f"{surname} household",
        9,
        family,
        accounts,
        [TaxUnit(ids.tax_unit(1), "married_filing_jointly", (primary.person_id, spouse.person_id))],
        [BillingGroup(ids.billing_group(1), "FS-STD", account_ids)],
        [advisory(ids, 1, family, (primary.person_id, spouse.person_id), account_ids, opened)],
        configured=opened,
        beneficiaries=tuple(beneficiaries),
    )
    return HouseholdScript(
        source=f"background/{household_id}",
        household=hh,
        pair=spec.pair,
        role="trap" if washed else "twin",
        accounts=tuple(scripts),
        activity=tuple(sorted(activity, key=lambda a: a.day)),
        planted=planted,
        twin=twin,
        background=True,
    )


def generate_pair(spec: PairSpec, market: Market) -> tuple[HouseholdScript, HouseholdScript]:
    trap = fit_ips(_draw(spec, market, spec.trap_id, washed=True), market)
    twin = fit_ips(_draw(spec, market, spec.twin_id, washed=False), market)
    return trap, twin
