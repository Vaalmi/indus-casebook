"""What every archetype's background generator draws with: IDs, people, accounts, holdings, the
standard fee schedule, and an IPS fitted to what the household holds.

A background pair is drawn from the seed, never copied from its featured pair, so a private task
on it cannot be matched to a public one by its figures.
"""

import random
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any

from casebook.generate.script import AccountScript, HouseholdScript, validate_script
from casebook.generate.simulate import simulate
from casebook.model.dates import SCENARIO_DATE
from casebook.model.household import (
    Account,
    Agreement,
    AllocationTarget,
    Beneficiary,
    BillingGroup,
    Disclosure,
    FeeSchedule,
    FeeTier,
    Household,
    Income,
    IraBasis,
    LossCarryforward,
    Ownership,
    Person,
    TaxProfile,
    TaxUnit,
)
from casebook.model.money import cents
from casebook.plant.common import account_value
from casebook.replay import replay
from casebook.securities.market import Market
from casebook.securities.master import load_master

ZERO = Decimal(0)
TAX_PROFILE_KNOWN = date(2025, 4, 15)
BAND = Decimal("0.05")

FIRST_NAMES = [
    "Abena",
    "Adrian",
    "Aisha",
    "Alejandro",
    "Amara",
    "Anders",
    "Anika",
    "Aryan",
    "Beatrix",
    "Bilal",
    "Camille",
    "Chidi",
    "Clara",
    "Dalia",
    "Darius",
    "Elif",
    "Emeka",
    "Esther",
    "Farid",
    "Fatima",
    "Felix",
    "Freya",
    "Gideon",
    "Hana",
    "Hugo",
    "Imani",
    "Ines",
    "Isaac",
    "Jasper",
    "Jun",
    "Kamala",
    "Kenji",
    "Laila",
    "Leon",
    "Lucia",
    "Malik",
    "Mareike",
    "Mateus",
    "Mei",
    "Mira",
    "Nadia",
    "Nikhil",
    "Noor",
    "Olumide",
    "Omar",
    "Orla",
    "Paulo",
    "Priyanka",
    "Quentin",
    "Rafaela",
    "Rohan",
    "Rosa",
    "Saoirse",
    "Selim",
    "Signe",
    "Tariq",
    "Thandi",
    "Tomasz",
    "Una",
    "Valentina",
    "Wen",
    "Xavier",
    "Yara",
    "Yusuf",
    "Zainab",
    "Zoltan",
]
SURNAMES = [
    "Abernathy",
    "Achebe",
    "Aldana",
    "Amundsen",
    "Bakshi",
    "Barros",
    "Bellweather",
    "Brannigan",
    "Castellane",
    "Chaudhry",
    "Dagher",
    "Delacroix",
    "Duarte",
    "Eklund",
    "Fairbairn",
    "Fonseca",
    "Galloway",
    "Grimaldi",
    "Haddad",
    "Halloran",
    "Ishikawa",
    "Iversen",
    "Jablonski",
    "Kaczmarek",
    "Kalinowski",
    "Kowalczyk",
    "Lachapelle",
    "Lindgren",
    "Mahlangu",
    "Marchbank",
    "Moreau",
    "Nakashima",
    "Nwachukwu",
    "Okonkwo",
    "Ostrowski",
    "Pacheco",
    "Pellegrini",
    "Quarshie",
    "Rasmussen",
    "Rautenbach",
    "Sabharwal",
    "Santangelo",
    "Sorensen",
    "Tamura",
    "Thorne",
    "Trevelyan",
    "Udeh",
    "Valderrama",
    "Varga",
    "Vinterberg",
    "Wainwright",
    "Whitcombe",
    "Yamaguchi",
    "Yilmaz",
    "Zabala",
    "Zelinski",
]
CHARITIES = (
    "Brookmere Community Pantry",
    "Halden Valley Literacy Trust",
    "Ottercliff Animal Rescue",
    "Pellow Street Shelter",
    "Quarrymoor Arts Collective",
    "Saltmarsh Youth Orchestra",
)
EMPLOYERS = (
    "Aldermoor Logistics",
    "Brightwater Instruments",
    "Calderon Freight",
    "Dunholt Engineering",
    "Fenmarch Health System",
    "Glenrock Software",
    "Hollin Bay Hospital",
    "Larchfield University",
)

STANDARD_SCHEDULE = FeeSchedule(
    schedule_id="FS-STD",
    basis="Quarterly in arrears on the quarter-end value of positions plus cash, per billing group",
    tiers=(
        FeeTier(Decimal(1_000_000), Decimal("0.0100")),
        FeeTier(Decimal(2_000_000), Decimal("0.0080")),
        FeeTier(None, Decimal("0.0060")),
    ),
)


def asset_class(security_id: str) -> str:
    """The IPS asset class of one of the master's securities, from its invented name."""
    alias = next(s.alias for s in load_master() if s.internal_id == security_id)
    if any(w in alias for w in ("Bond", "Inflation", "Muni")):
        return "Fixed income"
    if "Real Estate" in alias or "Properties" in alias:
        return "Real estate"
    if any(w in alias for w in ("International", "World", "Developed", "Emerging")):
        return "International equity"
    return "US equity"


# Securities by role, from the master (docs: src/casebook/securities/master.json).
US_FUNDS = ("SEC-0001", "SEC-0013", "SEC-0019", "SEC-0026", "SEC-0027", "SEC-0010", "SEC-0020", "SEC-0017", "SEC-0025")
INTERNATIONAL_FUNDS = ("SEC-0002", "SEC-0006", "SEC-0007", "SEC-0016", "SEC-0021")
BOND_FUNDS = ("SEC-0003", "SEC-0014", "SEC-0018", "SEC-0011", "SEC-0022", "SEC-0012")
MUNI_FUNDS = ("SEC-0008", "SEC-0015")
STOCKS = (*(f"SEC-{n:04d}" for n in range(28, 50)), "SEC-0004", "SEC-0005")


@dataclass(frozen=True)
class Ids:
    """The IDs inside one household, from its household ID: HH-0123 gives P-0123-1, SYN-01230001."""

    household_id: str

    @property
    def digits(self) -> str:
        return self.household_id.removeprefix("HH-")

    def person(self, k: int) -> str:
        return f"P-{self.digits}-{k}"

    def account(self, k: int) -> str:
        return f"SYN-{self.digits}{k:04d}"

    def lot(self, account: int, j: int) -> str:
        return f"L-{self.digits}{account:04d}-{j:02d}"

    def agreement(self, k: int) -> str:
        return f"AGR-{self.digits}-{k}"

    def billing_group(self, k: int) -> str:
        return f"BG-{self.digits}-{k}"

    def tax_unit(self, k: int) -> str:
        return f"TU-{self.digits}-{k}"

    def activity(self, k: int) -> str:
        return f"CA-{self.digits}-{k:02d}"

    def tax_id(self, k: int) -> str:
        """In area 000, which is never issued."""
        return f"000-{self.digits[:2]}-{self.digits[2:]}{k:02d}"


@dataclass(frozen=True)
class PairSpec:
    """One background pair to draw: its archetype and pair number, its two household IDs, the item
    ID its trap's planted item takes, and the random stream it draws from."""

    archetype: int
    pair: int
    trap_id: str
    twin_id: str
    item_id: str
    rng: random.Random


def born_between(rng: random.Random, first: date, last: date) -> date:
    return first + timedelta(days=rng.randint(0, (last - first).days))


def day_between(rng: random.Random, first: date, last: date) -> date:
    """A weekday between two days (markets price weekdays only)."""
    while True:
        day = born_between(rng, first, last)
        if day.weekday() < 5:
            return day


def person(
    rng: random.Random, ids: Ids, k: int, relationship: str, born: date, surname: str, died: date | None = None
) -> Person:
    first = rng.choice(FIRST_NAMES)
    name = f"{first} {surname}"
    return Person(
        person_id=ids.person(k),
        name=name,
        born=born,
        relationship=relationship,
        email=f"{first.lower()}.{surname.lower().replace(' ', '')}@mail.example",
        phone=f"555-01{rng.randint(0, 99):02d}",
        tax_id=ids.tax_id(k),
        died=died,
    )


def amount(rng: random.Random, low: int, high: int, step: int = 1000) -> Decimal:
    """A round amount between low and high, in dollars and cents, as the files write money."""
    return cents(Decimal(rng.randrange(low // step, high // step + 1) * step))


def holding_rows(
    rng: random.Random,
    ids: Ids,
    account: int,
    picks: list[tuple[str, Decimal]],
    acquired_from: date = date(2012, 1, 1),
    acquired_to: date = date(2024, 6, 28),
    basis: tuple[int, int] = (45, 115),
) -> list[dict[str, Any]]:
    """Opening holdings for one account: (security, value) picks, each with an acquired day and a
    basis as a percentage of its 31 December 2024 value. Returned as plain rows for `account_script`."""
    return [
        {
            "lot_id": ids.lot(account, j),
            "security_id": security,
            "value": value,
            "acquired": day_between(rng, acquired_from, acquired_to),
            "basis_pct": Decimal(rng.randint(*basis)),
        }
        for j, (security, value) in enumerate(picks, start=1)
    ]


def account_script(account_id: str, cash: Decimal, rows: list[dict[str, Any]]) -> AccountScript:
    from casebook.generate.script import Holding

    return AccountScript(
        account_id,
        cash,
        tuple(Holding(r["lot_id"], r["security_id"], r["value"], r["acquired"], r["basis_pct"]) for r in rows),
    )


def advisory(
    ids: Ids, k: int, household: list[Person], party_ids: tuple[str, ...], account_ids: tuple[str, ...], signed: date
) -> Agreement:
    names = [p.name.split()[0] for p in household if p.person_id in party_ids]
    who = names[0] if len(names) == 1 else " and ".join(names)
    return Agreement(
        ids.agreement(k),
        "advisory",
        party_ids,
        account_ids,
        signed,
        f"Advisory agreement for {who}'s accounts on the standard fee schedule.",
    )


def household(
    ids: Ids,
    name: str,
    archetype: int,
    members: list[Person],
    accounts: list[tuple[Account, tuple[str, ...]]],
    tax_units: list[TaxUnit],
    billing_groups: list[BillingGroup],
    agreements: list[Agreement],
    configured: date,
    beneficiaries: tuple[Beneficiary, ...] = (),
    **extra: Any,
) -> Household:
    """A household with the defaults every background household shares: the standard schedule, each
    person told about the accounts they own, a carried-in tax profile of zeros, and an IPS that
    `fit_ips` replaces once the household's holdings are known."""
    told: dict[str, list[str]] = defaultdict(list)
    for account, owners in accounts:
        for owner in owners:
            told[owner].append(account.account_id)
    fields: dict[str, Any] = {
        "household_id": ids.household_id,
        "name": name,
        "archetype": archetype,
        "members": tuple(members),
        "accounts": tuple(a for a, _ in accounts),
        "ownership": tuple(Ownership(a.account_id, owners) for a, owners in accounts),
        "tax_units": tuple(tax_units),
        "billing_groups": tuple(billing_groups),
        "disclosures": tuple(Disclosure(p, tuple(sorted(a))) for p, a in sorted(told.items())),
        "agreements": tuple(agreements),
        "beneficiaries": beneficiaries,
        "income": (),
        "crm_activities": (),
        "fee_schedule": STANDARD_SCHEDULE,
        "allocation": (),
        "asset_classes": {},
        "restrictions": (),
        "concentration_limit": Decimal("0.25"),
        "tax_profile": TaxProfile(
            TAX_PROFILE_KNOWN,
            tuple(LossCarryforward(t.tax_unit_id, ZERO, ZERO) for t in tax_units),
            tuple(
                IraBasis(p, ZERO)
                for p in sorted({o for a, owners in accounts if "ira" in a.account_type for o in owners})
            ),
        ),
        "configured": configured,
    }
    fields.update(extra)
    return Household(**fields)


def fit_ips(script: HouseholdScript, market: Market, concentration_limit: Decimal | None = None) -> HouseholdScript:
    """Give the household an IPS its holdings meet on the scenario date: each asset class's target is
    its weight then, within a band of five points, so nothing drifts; the concentration limit sits
    above every security's share unless the archetype sets one for its trap to cross."""
    held = replay(simulate(script, market).events, (SCENARIO_DATE,)).snapshots[SCENARIO_DATE]
    by_security: dict[str, Decimal] = defaultdict(lambda: ZERO)
    total = ZERO
    for account in script.household.accounts:
        total += account_value(held, account.account_id, market)
        for security, units in held.holdings(account.account_id).items():
            by_security[security] += cents(units * market.price(security, SCENARIO_DATE))
    by_class: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for security, value in by_security.items():
        by_class[asset_class(security)] += value
    targets = tuple(
        AllocationTarget(cls, (value / total).quantize(Decimal("0.01")), BAND)
        for cls, value in sorted(by_class.items())
    )
    largest = max(by_security.values(), default=ZERO) / total if total else ZERO
    limit = concentration_limit or max(
        Decimal("0.25"), (largest + Decimal("0.05")).quantize(Decimal("0.01"), ROUND_CEILING)
    )
    household = replace(
        script.household,
        allocation=targets,
        asset_classes={s: asset_class(s) for s in sorted(by_security)},
        concentration_limit=limit,
    )
    fitted = replace(script, household=household)
    validate_script(fitted)
    return fitted


SOCIAL_SECURITY_FROM_AGE = 67


def with_social_security(rng: random.Random, script: HouseholdScript) -> HouseholdScript:
    """Give each living member of 67 or over at the end of 2025 a year of Social Security benefits:
    a monthly benefit drawn from $1,400 to $3,800, times twelve (SSA-1099 box 5)."""
    lines = tuple(
        Income(
            p.person_id,
            "social_security",
            "Social Security Administration",
            cents(Decimal(rng.randint(1400, 3800) * 12)),
            2025,
        )
        for p in script.household.members
        if p.died is None and 2025 - p.born.year >= SOCIAL_SECURITY_FROM_AGE
    )
    if not lines:
        return script
    return replace(script, household=replace(script.household, income=(*script.household.income, *lines)))
