"""Archetype 2 drawn: a December sale of a long-held fund pushes modified AGI over the net
investment income tax threshold (trap), and a smaller December sale that leaves it just under
(near-miss twin). Both hold a bond fund in the taxable account and only equity funds in the IRAs.

The wages are set last: the holdings and the sale are drawn, the household is simulated for its
dividends and realized gain, and the wages are then chosen so that the sale, and only the sale,
crosses the threshold (or, in the twin, so that modified AGI stays within the near-miss margin).
"""

from dataclasses import replace
from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal

from casebook.generate.background.common import (
    BOND_FUNDS,
    EMPLOYERS,
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
from casebook.generate.simulate import simulate
from casebook.model.dates import PRIOR_YEAR_END, QUARTER_ENDS, SCENARIO_DATE, add_weekdays
from casebook.model.events import Sell
from casebook.model.household import Account, Beneficiary, BillingGroup, CrmActivity, Income, Person, TaxUnit
from casebook.model.money import cents, usd
from casebook.plant import PlantContext, PlantError
from casebook.plant.a02_niit import ITEM_TYPE, NEAR_MISS_MARGIN, TAX_YEAR, workings
from casebook.replay import replay
from casebook.securities.market import Market

WAGE_STEP = Decimal(100)
LONG_HELD = (25, 50)
EARLY = timedelta(days=730)  # The sold fund's basis, as a percentage of its value at the end of 2024.


def _floor(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).quantize(Decimal(1), rounding=ROUND_FLOOR) * step


def _first(p: Person) -> str:
    return p.name.split()[0]


def _sale_units(market: Market, security: str, value: Decimal, basis_pct: Decimal, day: date, gain: Decimal) -> Decimal:
    """Units of the long-held lot whose sale on `day` realizes about `gain`."""
    opening = market.price(security, PRIOR_YEAR_END)
    held = (value / opening).quantize(Decimal(1), rounding=ROUND_FLOOR)
    per_unit = market.price(security, day) - opening * basis_pct / 100
    if per_unit <= 0:
        raise PlantError(f"{security} is worth less on {day} than its basis, so its sale realizes no gain")
    units = min(held, (gain / per_unit).quantize(Decimal(1), rounding=ROUND_FLOOR))
    if units < 1:
        raise PlantError(f"a sale of {security} on {day} realizing {usd(gain)} is under one unit")
    return units


def _draw(spec: PairSpec, market: Market, household_id: str, trap: bool) -> HouseholdScript:
    """The household with no wages yet; `_set_wages` adds them once the year is simulated."""
    rng, ids = spec.rng, Ids(household_id)
    surname = rng.choice(SURNAMES)
    married = rng.random() < 0.7
    primary = person(rng, ids, 1, "primary", born_between(rng, date(1962, 1, 1), date(1979, 12, 31)), surname)
    family: list[Person] = [primary]
    if married:
        spouse_surname = surname if rng.random() < 0.5 else rng.choice(SURNAMES)
        family.append(
            person(rng, ids, 2, "spouse", born_between(rng, date(1961, 1, 1), date(1980, 12, 31)), spouse_surname)
        )
    configured = day_between(rng, date(2003, 1, 6), date(2014, 12, 15))
    if married:
        taxable = Account(ids.account(1), "joint_taxable", "Joint tenants with right of survivorship", configured)
    else:
        taxable = Account(ids.account(1), "individual_taxable", f"Individual, {primary.name}", configured)
    iras = [
        Account(
            ids.account(k),
            "traditional_ira",
            f"Traditional IRA, {p.name}",
            day_between(rng, date(1996, 1, 8), date(2012, 12, 14)),
        )
        for k, p in enumerate(family, start=2)
    ]
    accounts = [(taxable, tuple(p.person_id for p in family))] + [
        (ira, (p.person_id,)) for ira, p in zip(iras, family, strict=True)
    ]

    sold, other, ira_us = rng.sample(US_FUNDS, 3)
    intl, bond = rng.choice(INTERNATIONAL_FUNDS), rng.choice(BOND_FUNDS)
    sold_value = amount(rng, 150000, 320000, step=10)
    taxable_rows = holding_rows(
        rng,
        ids,
        1,
        [
            (bond, amount(rng, 140000, 300000, step=10)),
            (sold, sold_value),
            (other, amount(rng, 60000, 150000, step=10)),
            (intl, amount(rng, 40000, 110000, step=10)),
        ],
        acquired_from=configured,
    )
    # The sold fund is the account's first purchase, long held and far below its value.
    sold_basis = Decimal(rng.randint(*LONG_HELD))
    held_since = day_between(rng, configured, configured + EARLY)
    taxable_rows[1] |= {"acquired": held_since, "basis_pct": sold_basis}
    scripts = [account_script(taxable.account_id, amount(rng, 20000, 50000, step=10), taxable_rows)]
    for k, ira in enumerate(iras, start=2):
        scripts.append(
            account_script(
                ira.account_id,
                amount(rng, 2000, 9000, step=10),
                holding_rows(
                    rng,
                    ids,
                    k,
                    [(ira_us, amount(rng, 90000, 260000, step=10)), (intl, amount(rng, 30000, 90000, step=10))],
                    acquired_from=ira.opened,
                    basis=(100, 100),
                ),
            )
        )

    sale_day = day_between(rng, date(2025, 12, 1), date(2025, 12, 17))
    gain = amount(rng, 25000, 85000, step=10) if trap else amount(rng, 3000, 14000, step=10)
    units = _sale_units(market, sold, sold_value, sold_basis, sale_day, gain)
    proceeds = cents(units * market.price(sold, sale_day))
    withdrawn = _floor(proceeds * Decimal(rng.randint(30, 80)) / 100, Decimal(1000))
    ira_buy = day_between(rng, date(2025, 2, 3), date(2025, 5, 30))
    ira_units = Decimal(rng.randint(3, 12))
    activity = (
        Activity("buy", ira_buy, iras[0].account_id, security_id=ira_us, units=ira_units),
        Activity("sell", sale_day, taxable.account_id, security_id=sold, units=units),
        Activity("withdrawal", add_weekdays(sale_day, rng.randint(3, 6)), taxable.account_id, amount=withdrawn),
    )

    reason = rng.choice(("a child's spring tuition", "a new roof", "a family wedding", "a down payment for a child"))
    crm = (
        CrmActivity(
            ids.activity(1),
            day_between(rng, date(2025, 11, 17), date(2025, 11, 28)),
            "call",
            f"{_first(primary)} called to ask for cash from the taxable account {taxable.account_id} for {reason}. "
            f"Agreed to sell part of the fund held there since {held_since.year}.",
        ),
    )
    planted = twin = None
    filing = "married_filing_jointly" if married else "single"
    unit = TaxUnit(ids.tax_unit(1), filing, tuple(p.person_id for p in family))
    if trap:
        planted = PlantedSpec(
            spec.item_id,
            ITEM_TYPE,
            {"tax_unit_id": unit.tax_unit_id, "sale_date": sale_day.isoformat(), "security_id": sold},
        )
    else:
        twin = TwinSpec("near_miss", "")  # Its explanation names modified AGI, known once the wages are set.
    beneficiaries: list[Beneficiary] = []
    for ira, owner in zip(iras, family, strict=True):
        partner = next((p for p in family if p is not owner), None)
        if partner is not None:
            beneficiaries.append(
                Beneficiary(
                    ira.account_id, "primary", partner.name, "spouse", Decimal(100), partner.person_id, ira.opened
                )
            )
        else:
            heir = f"{rng.choice(FIRST_NAMES)} {surname}"
            beneficiaries.append(
                Beneficiary(ira.account_id, "primary", heir, "sibling", Decimal(100), None, ira.opened)
            )
    all_accounts = tuple(a.account_id for a, _ in accounts)
    hh = household(
        ids,
        f"{surname} household",
        2,
        family,
        accounts,
        [unit],
        [BillingGroup(ids.billing_group(1), "FS-STD", all_accounts)],
        [advisory(ids, 1, family, unit.person_ids, all_accounts, configured)],
        configured=configured,
        beneficiaries=tuple(beneficiaries),
        crm_activities=crm,
    )
    return HouseholdScript(
        source=f"background/{household_id}",
        household=hh,
        pair=spec.pair,
        role="trap" if trap else "twin",
        accounts=tuple(scripts),
        activity=activity,
        planted=planted,
        twin=twin,
        background=True,
    )


def _set_wages(spec: PairSpec, market: Market, script: HouseholdScript, trap: bool) -> HouseholdScript:
    """Simulate the year, then choose wages so the sale alone crosses the threshold (trap) or
    modified AGI stays under it by no more than the near-miss margin (twin)."""
    rng, hh = spec.rng, script.household
    simulation = simulate(script, market)
    context = PlantContext(
        script,
        simulation.events,
        replay(simulation.events, (*QUARTER_ENDS, SCENARIO_DATE)),
        simulation.quarters,
        market,
    )
    unit = hh.tax_units[0]
    w = workings(context, unit)
    sale = next(e for e in simulation.events if isinstance(e, Sell))
    sale_gain = sum(
        (lot.proceeds - lot.cost for lot in context.replayed.closed if lot.event_id == sale.event_id), Decimal(0)
    )
    if trap:
        over = sale_gain * Decimal(rng.randint(15, 85)) / 100
        total = _floor(w.threshold - w.net_investment_income + over, WAGE_STEP)
        magi = total + w.net_investment_income
        if not (magi > w.threshold and magi - sale_gain <= w.threshold):
            raise PlantError(f"{script.source}: wages of {usd(total)} do not make the sale the crossing")
    else:
        under = amount(rng, 1000, int(NEAR_MISS_MARGIN) - 2000, step=10)
        total = _floor(w.threshold - w.net_investment_income - under, WAGE_STEP)
        magi = total + w.net_investment_income
    members = [hh.person(p) for p in unit.person_ids]
    if len(members) == 1:
        split = [total]
    else:
        first = _floor(total * Decimal(rng.randint(35, 65)) / 100, WAGE_STEP)
        split = [first, total - first]
    payers = rng.sample(EMPLOYERS, len(members))
    income = tuple(
        Income(p.person_id, "wages", payer, wage, TAX_YEAR)
        for p, payer, wage in zip(members, payers, split, strict=True)
    )
    w2 = CrmActivity(
        Ids(hh.household_id).activity(2),
        day_between(rng, date(2026, 1, 26), date(2026, 2, 27)),
        "document_received",
        "2025 Forms W-2 received: "
        + "; ".join(
            f"{_first(p)}, {payer}, wages {usd(wage)}" for p, payer, wage in zip(members, payers, split, strict=True)
        )
        + ". No other income outside the accounts.",
    )
    household_ = replace(hh, income=income, crm_activities=(*hh.crm_activities, w2))
    if trap:
        return replace(script, household=household_)
    filers = "joint filers" if unit.filing_status == "married_filing_jointly" else "single filers"
    who = " and ".join(_first(p) for p in members)
    iras = "the IRAs hold" if len(members) > 1 else "the IRA holds"
    held_since = min(lot.acquired for lot in context.replayed.closed if lot.event_id == sale.event_id)
    explanation = (
        f"A near miss. {who}'s wages are a little under the net investment income tax threshold for {filers}, the "
        f"taxable account pays dividends, and in December 2025 part of a fund held since {held_since.year} was sold "
        f"at a gain. That looks like the threshold trap, but the sale was small: wages plus the dividends and the "
        f"gain in the taxable account, the only income, make modified AGI {usd(magi)}, under the "
        f"{usd(w.threshold)} threshold, so no net investment income tax is owed for 2025. Dividends inside the "
        f"retirement accounts are not income. The SALT limit applies in full. The bond fund in the taxable account "
        f"while {iras} equity funds is still worth raising as asset location."
    )
    return replace(script, household=household_, twin=TwinSpec("near_miss", explanation))


def generate_pair(spec: PairSpec, market: Market) -> tuple[HouseholdScript, HouseholdScript]:
    trap = fit_ips(_draw(spec, market, spec.trap_id, trap=True), market)
    twin = fit_ips(_draw(spec, market, spec.twin_id, trap=False), market)
    return _set_wages(spec, market, trap, trap=True), _set_wages(spec, market, twin, trap=False)
