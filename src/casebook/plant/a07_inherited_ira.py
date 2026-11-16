"""Archetype 7. Inherited-IRA beneficiary: the ten-year rule and whether annual distributions apply.

The trap's parent died after the required beginning date, so the beneficiary owes an annual RMD
in years 1 to 9 as well as emptying the account by the end of year 10; nothing was taken in 2025.
The near-miss twin's parent died before it, so only the ten-year deadline applies.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from casebook.model.files import ACCOUNTS_CSV, CASH_CSV, CRM_JSON, POSITIONS_CSV, TRANSACTIONS_CSV
from casebook.model.household import Decedent, Person
from casebook.model.money import cents, usd
from casebook.model.registry import FigureTable, RegistryEntry
from casebook.plant.a05_first_rmd import (
    DISTRIBUTION_YEAR,
    age_in,
    distributions_for,
    gross,
    prior_year_end_balance,
    required_beginning_date,
)
from casebook.plant.common import PlantContext, PlantError, Planting
from casebook.rules import load_rules

ITEM_TYPE = "inherited_ira_annual_rmd"
INHERITED = "inherited_ira"
SINGLE_LIFE = "single_life"
YEAR_END = date(DISTRIBUTION_YEAR, 12, 31)


@dataclass(frozen=True)
class Inheritance:
    account_id: str
    beneficiary: Person
    decedent: Decedent
    rbd: date
    final_year: int

    @property
    def after_rbd(self) -> bool:
        return self.decedent.died >= self.rbd


def _inheritance(context: PlantContext) -> Inheritance:
    hh, rules = context.script.household, load_rules(DISTRIBUTION_YEAR)
    inherited = [a for a in hh.accounts if a.account_type == INHERITED]
    if len(inherited) != 1:
        raise PlantError(f"{hh.household_id}: archetype 7 has one inherited IRA, not {len(inherited)}")
    account = inherited[0]
    assert account.inherited_from is not None
    decedent = account.inherited_from
    owners = hh.owners(account.account_id)
    if len(owners) != 1:
        raise PlantError(f"{hh.household_id}: an inherited IRA has one beneficiary as owner")
    beneficiary = hh.person(owners[0])
    # A child of the decedent is an eligible designated beneficiary, outside the ten-year rule, while a
    # minor or when not more than ten years younger than the decedent.
    b, d = beneficiary.born, decedent.born
    younger_by, majority = int(rules.value("eligible_beneficiary_years")), int(rules.value("age_of_majority"))
    if (b.year - younger_by, b.month, b.day) <= (d.year, d.month, d.day) or age_in(
        beneficiary.born, decedent.died.year
    ) < majority:
        raise PlantError(
            f"{hh.household_id}: {beneficiary.name} is an eligible designated beneficiary "
            "(not more than ten years younger than the decedent, or a minor), outside the ten-year rule"
        )
    final_year = decedent.died.year + int(rules.value("inherited_ira_years"))
    if not decedent.died.year < DISTRIBUTION_YEAR < final_year:
        raise PlantError(f"{hh.household_id}: {DISTRIBUTION_YEAR} is not one of years 1 to 9 after the death")
    return Inheritance(
        account.account_id, beneficiary, decedent, required_beginning_date(rules, decedent.born), final_year
    )


def plant_trap(context: PlantContext) -> Planting:
    script = context.script
    assert script.planted is not None
    hh, spec, rules = script.household, script.planted, load_rules(DISTRIBUTION_YEAR)
    heir = _inheritance(context)
    ben, dec = heir.beneficiary, heir.decedent
    if not heir.after_rbd:
        raise PlantError(
            f"{spec.item_id}: {dec.name} died on {dec.died} before the required beginning date {heir.rbd}, "
            "so no annual distributions are due"
        )
    enforced = int(rules.value("annual_rmd_enforced_from"))
    if enforced > DISTRIBUTION_YEAR:
        raise PlantError(f"{spec.item_id}: annual distributions are enforced only from {enforced}")
    first_year = dec.died.year + 1
    ben_age = age_in(ben.born, first_year)
    ben_start = rules.factor(SINGLE_LIFE, ben_age)
    ben_period = ben_start - (DISTRIBUTION_YEAR - first_year)
    dec_age = age_in(dec.born, dec.died.year)
    dec_start = rules.factor(SINGLE_LIFE, dec_age)
    dec_period = dec_start - (DISTRIBUTION_YEAR - dec.died.year)
    period = max(ben_period, dec_period)
    whose = ben.name if period == ben_period else dec.name
    balance = prior_year_end_balance(context, heir.account_id)
    rmd = cents(balance / period)
    paid = distributions_for(context, heir.account_id, DISTRIBUTION_YEAR, YEAR_END)
    taken = gross(paid)
    if taken >= rmd:
        raise PlantError(f"{spec.item_id}: {usd(taken)} was taken in {DISTRIBUTION_YEAR}, meeting the RMD")
    missed = rmd - taken
    next_balance = context.value(heir.account_id, YEAR_END)
    next_rmd = cents(next_balance / (period - 1))
    death = dec.died.isoformat()
    conclusion = (
        f"{ben.name}, born {ben.born.isoformat()}, owns inherited IRA {heir.account_id} from {dec.name}, born "
        f"{dec.born.isoformat()}, who died on {death} (the registration, and the death certificate in the CRM). "
        f"{dec.name}'s required beginning date was {heir.rbd.isoformat()}, so the death came after it. "
        f"{ben.name} is a designated "
        "beneficiary but not an eligible designated beneficiary: more than ten years younger than the decedent and "
        f"not a minor. So the ten-year rule applies (26 U.S.C. § 401(a)(9)(H)(i)): the account must be emptied by "
        f"{heir.final_year}-12-31. Because the death came after the required beginning date, the final regulations "
        f"also require an annual RMD in each year from {first_year} to {heir.final_year - 1} (26 CFR "
        f"1.401(a)(9)-5(d)). They apply from {enforced}; IRS Notice 2024-35 waived the excise tax for earlier years, "
        f"so {DISTRIBUTION_YEAR} is the first year a missed annual RMD counts. The {DISTRIBUTION_YEAR} RMD is the "
        f"31 December 2024 balance of {usd(balance)} divided by the distribution period, the longer of "
        f"{ben.name}'s single life expectancy ({ben_start} at age {ben_age} in {first_year}, less "
        f"{DISTRIBUTION_YEAR - first_year}: {ben_period}) and {dec.name}'s remaining life expectancy ({dec_start} at "
        f"age {dec_age} in {dec.died.year}, less {DISTRIBUTION_YEAR - dec.died.year}: {dec_period}). {whose}'s "
        f"{period} applies, so the {DISTRIBUTION_YEAR} RMD was {usd(rmd)}. {usd(taken)} was distributed in "
        f"{DISTRIBUTION_YEAR}, so {usd(missed)} was missed. The shortfall is subject to the excise tax of "
        "26 U.S.C. § 4974(a), reported on Form 5329, which is reduced if it is distributed within the correction "
        "window of § 4974(e) and may be waived for reasonable error under § 4974(d). "
        f"{ben.name} should take the {usd(missed)} now, and the {DISTRIBUTION_YEAR + 1} RMD by "
        f"{DISTRIBUTION_YEAR + 1}-12-31: the 31 December {DISTRIBUTION_YEAR} balance of {usd(next_balance)} divided "
        f"by {period - 1}, {usd(next_rmd)}."
    )
    entry = RegistryEntry(
        item_id=spec.item_id,
        household_id=hh.household_id,
        kind="situation",
        item_type=spec.item_type,
        title="Inherited IRA: annual RMDs apply under the ten-year rule, and the 2025 RMD was not taken",
        sources=(ACCOUNTS_CSV, POSITIONS_CSV, CASH_CSV, TRANSACTIONS_CSV, CRM_JSON),
        conclusion=conclusion,
        figures=(
            ("Decedent's required beginning date", heir.rbd.isoformat()),
            ("Account to be emptied by", f"{heir.final_year}-12-31"),
            ("Distribution period", str(period)),
            (f"{DISTRIBUTION_YEAR} RMD", usd(rmd)),
            (f"Taken in {DISTRIBUTION_YEAR}", usd(taken)),
            (f"{DISTRIBUTION_YEAR} RMD missed", usd(missed)),
            (f"{DISTRIBUTION_YEAR + 1} RMD", usd(next_rmd)),
        ),
        table=FigureTable(
            columns=("Working", "Value"),
            rows=(
                (f"Balance of {heir.account_id} on 2024-12-31", usd(balance)),
                (f"{ben.name}: single life factor at age {ben_age} in {first_year}", str(ben_start)),
                (f"{ben.name}: less {DISTRIBUTION_YEAR - first_year} for {DISTRIBUTION_YEAR}", str(ben_period)),
                (f"{dec.name}: single life factor at age {dec_age} in {dec.died.year}", str(dec_start)),
                (f"{dec.name}: less {DISTRIBUTION_YEAR - dec.died.year} for {DISTRIBUTION_YEAR}", str(dec_period)),
                ("Distribution period (the longer)", str(period)),
                (f"{DISTRIBUTION_YEAR} RMD", usd(rmd)),
                (f"Taken in {DISTRIBUTION_YEAR}", usd(taken)),
                (f"Balance of {heir.account_id} on {YEAR_END.isoformat()}", usd(next_balance)),
                (f"{DISTRIBUTION_YEAR + 1} RMD, period {period - 1}", usd(next_rmd)),
            ),
        ),
        known_as_of=YEAR_END + timedelta(days=1),
        references=(ben.person_id, heir.account_id),
    )
    return Planting(entries=(entry,))


def check_twin(context: PlantContext, kind: str) -> Planting:
    """A near miss: nothing taken in 2025, as in the trap, but the death came before the decedent's
    required beginning date, so only the ten-year deadline applies."""
    hh = context.script.household
    if kind != "near_miss":
        raise PlantError(f"{hh.household_id}: archetype 7's twin is a near miss, not {kind!r}")
    heir = _inheritance(context)
    if heir.after_rbd:
        raise PlantError(
            f"{hh.household_id}: {heir.decedent.name} died on {heir.decedent.died}, on or after the required "
            f"beginning date {heir.rbd}, so annual distributions are due"
        )
    taken = gross(distributions_for(context, heir.account_id, DISTRIBUTION_YEAR, YEAR_END))
    if taken:
        raise PlantError(f"{hh.household_id}: {usd(taken)} was taken in {DISTRIBUTION_YEAR}, so nothing looks missed")
    return Planting()
