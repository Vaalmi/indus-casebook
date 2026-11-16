"""A household's 2025 required minimum distributions, worked from its emitted files.

Who owes: a traditional IRA's or a 401(k)'s owner who has reached the applicable age by the end of
2025, and the beneficiary of an inherited IRA whose decedent died on or after the decedent's own
required beginning date (the ten-year rule's annual distributions). How much: the account's 31
December 2024 balance (the custodian's positions on that day, at that day's prices, plus its cash)
divided by the Uniform Lifetime factor for the owner's age on their 2025 birthday, or by the
inherited IRA's distribution period. What counts: the account's distributions, QCDs and
withdrawals in 2025, and, in an owner's first distribution year, those made by the required
beginning date, 1 April 2026 (IRS Publication 590-B, "Distributions after the required beginning
date"). What meets what: an owner's traditional IRAs are met together, from any of them (26 CFR
1.408-8); a 401(k) only from itself; an inherited IRA only from itself.

The key reads the account register, the custodian's positions, cash and transactions, the
beneficiary designations, the portfolio system's people and the document index, with the 2025
rules table; it never reads how the book was built. A situation it does not cover (a joint-table
spouse, an eligible designated beneficiary, a still-working plan owner, a year-of-death RMD) raises
`UnsettledRmdError` rather than give an answer it cannot stand behind.
"""

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from casebook.keys.figures import KeyFigure
from casebook.model.dates import PRIOR_YEAR_END
from casebook.model.files import (
    ACCOUNTS_COLUMNS,
    ACCOUNTS_CSV,
    BENEFICIARIES_COLUMNS,
    BENEFICIARIES_CSV,
    DISTRIBUTION,
    DOCUMENTS_INDEX,
    PORTFOLIO_HOUSEHOLD,
    QCD,
    WITHDRAWAL,
    read_cash,
    read_csv,
    read_json,
    read_positions,
    read_transactions,
)
from casebook.model.money import cents, fmt
from casebook.rules import Rules, load_rules

YEAR = 2025
YEAR_START, YEAR_END = date(YEAR, 1, 1), date(YEAR, 12, 31)
TRADITIONAL_IRA, PLAN, INHERITED_IRA = "traditional_ira", "401k", "inherited_ira"
# What takes money out of a retirement account toward its RMD. A Roth conversion or a
# trustee-to-trustee transfer does not count toward one.
PAYOUT_TYPES = (DISTRIBUTION, QCD, WITHDRAWAL)
UNIFORM, SINGLE_LIFE = "uniform_lifetime", "single_life"
W2 = "form_w2"
ZERO = Decimal(0)
HALF = Decimal("0.5")
# The required beginning date is 1 April of the year after the owner reaches the applicable age
# (26 U.S.C. § 401(a)(9)(C)(i); for an IRA, § 408(a)(6)).
RBD_MONTH, RBD_DAY = 4, 1
# Which applicable age a birth date takes (26 U.S.C. § 401(a)(9)(C), as the SECURE Act and the
# SECURE 2.0 Act set it): 70½ before 1 July 1949, 72 to the end of 1950, 73 from 1951, 75 from
# 1960. The ages are the rules table's.
AGE_72_FROM, AGE_73_FROM, AGE_75_FROM = date(1949, 7, 1), date(1951, 1, 1), date(1960, 1, 1)
# The excise tax on a missed RMD: 25 percent of the shortfall (26 U.S.C. § 4974(a)), 10 percent if
# it is corrected within the correction window (§ 4974(e)). An answer may work either out.
EXCISE_RATES = (Decimal("0.25"), Decimal("0.10"))


# The finding a review of one household's RMDs reaches.
RMD_MISSED, ALL_RMDS_MET = "rmd_missed", "all_rmds_met"


class UnsettledRmdError(ValueError):
    """The household's files, or this key, cannot settle a 2025 RMD."""


@dataclass(frozen=True)
class Person:
    person_id: str
    name: str
    born: date
    died: date | None


@dataclass(frozen=True)
class Payout:
    """Money out of a retirement account, as the custodian's transactions record it."""

    transaction_id: str
    account_id: str
    day: date
    type: str
    amount: Decimal
    description: str


@dataclass(frozen=True)
class AccountRmd:
    """One account's 2025 RMD: its balance, the divisor and what it rests on, and what it paid."""

    account_id: str
    account_type: str
    owner_id: str
    balance: Decimal
    # The age the divisor is read at, and the divisor: the Uniform Lifetime factor, or an inherited
    # IRA's distribution period.
    age: int
    divisor: Decimal
    rmd: Decimal
    deadline: date
    payouts: tuple[Payout, ...]
    # An inherited IRA's decedent (name and dates): one beneficiary's inherited IRAs from the same decedent
    # may be met together (Pub. 590-B, "More than one IRA").
    inherited_from: str = ""

    @property
    def taken(self) -> Decimal:
        return sum((p.amount for p in self.payouts), ZERO)


@dataclass(frozen=True)
class Requirement:
    """What must be paid from which accounts by when: an owner's traditional IRAs together, or one
    401(k) or inherited IRA on its own."""

    owner_id: str
    account_type: str
    account_ids: tuple[str, ...]
    rmd: Decimal
    deadline: date
    taken: Decimal

    @property
    def met(self) -> bool:
        return self.taken >= self.rmd

    @property
    def shortfall(self) -> Decimal:
        return max(self.rmd - self.taken, ZERO)


@dataclass(frozen=True)
class HouseholdRmd:
    household_id: str
    people: tuple[Person, ...]
    accounts: tuple[AccountRmd, ...]
    requirements: tuple[Requirement, ...]
    computed_figures: tuple[KeyFigure, ...]
    # Ages, life-expectancy factors and distribution periods: read from the IRS tables, not the files.
    table_figures: tuple[Decimal, ...]

    @property
    def missed(self) -> tuple[Requirement, ...]:
        return tuple(r for r in self.requirements if not r.met)

    @property
    def total_shortfall(self) -> Decimal:
        return sum((r.shortfall for r in self.requirements), ZERO)

    @property
    def finding(self) -> str:
        return RMD_MISSED if self.missed else ALL_RMDS_MET

    def account(self, account_id: str) -> AccountRmd:
        return next(a for a in self.accounts if a.account_id == account_id)

    def person(self, person_id: str) -> Person:
        return next(p for p in self.people if p.person_id == person_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "household_id": self.household_id,
            "finding": self.finding,
            "total_shortfall": fmt(self.total_shortfall),
            "accounts": [
                {
                    "account_id": a.account_id,
                    "account_type": a.account_type,
                    "owner_id": a.owner_id,
                    "balance_2024_12_31": fmt(a.balance),
                    "age": a.age,
                    "divisor": fmt(a.divisor),
                    "rmd": fmt(a.rmd),
                    "deadline": a.deadline.isoformat(),
                    "payouts": [
                        {"transaction_id": p.transaction_id, "date": p.day.isoformat(), "type": p.type}
                        | {"amount": fmt(p.amount)}
                        for p in a.payouts
                    ],
                }
                for a in self.accounts
            ],
            "requirements": [
                {
                    "owner_id": r.owner_id,
                    "account_type": r.account_type,
                    "account_ids": list(r.account_ids),
                    "rmd": fmt(r.rmd),
                    "deadline": r.deadline.isoformat(),
                    "taken": fmt(r.taken),
                    "met": r.met,
                    "shortfall": fmt(r.shortfall),
                }
                for r in self.requirements
            ],
            "computed_figures": [{"label": f.label, "value": fmt(f.value)} for f in self.computed_figures],
        }


def attains(born: date, age: Decimal) -> date:
    """The day a person attains a whole or half-year age: 70½ is six calendar months after the 70th birthday."""
    years = int(age)
    months = 6 if age - years == HALF else 0
    month = born.month - 1 + months
    year = born.year + years + month // 12
    month = month % 12 + 1
    return date(year, month, min(born.day, calendar.monthrange(year, month)[1]))


def applicable_age(rules: Rules, born: date) -> Decimal:
    if born < AGE_72_FROM:
        return rules.value("rmd_age_before_secure")
    if born < AGE_73_FROM:
        return rules.value("rmd_age_secure")
    if born < AGE_75_FROM:
        return rules.value("rmd_age")
    return rules.value("rmd_age_from_1960")


def first_distribution_year(rules: Rules, born: date) -> int:
    return attains(born, applicable_age(rules, born)).year


def required_beginning(rules: Rules, born: date) -> date:
    return date(first_distribution_year(rules, born) + 1, RBD_MONTH, RBD_DAY)


def _people(root: Path) -> dict[str, Person]:
    raw = read_json(root, PORTFOLIO_HOUSEHOLD)
    return {
        str(m["person_id"]): Person(
            str(m["person_id"]),
            str(m["name"]),
            date.fromisoformat(str(m["born"])),
            date.fromisoformat(str(m["died"])) if m.get("died") else None,
        )
        for m in raw["household_membership"]
    }


def _owners(root: Path) -> dict[str, tuple[str, ...]]:
    raw = read_json(root, PORTFOLIO_HOUSEHOLD)
    return {str(o["account_id"]): tuple(str(p) for p in o["owner_ids"]) for o in raw["legal_ownership"]}


def _balances(root: Path, day: date) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """Each account's positions and cash at the end of `day`; an account with no cash row is absent."""
    held: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for row in read_positions(root):
        if row.valuation_date == day:
            held[row.account_id] += row.market_value
    cash = {r.account_id: r.settled_cash + r.unsettled_cash for r in read_cash(root) if r.valuation_date == day}
    return dict(held), cash


def _payouts(root: Path) -> dict[str, list[Payout]]:
    found: dict[str, list[Payout]] = defaultdict(list)
    for t in read_transactions(root):
        if t.type in PAYOUT_TYPES and t.amount < 0:
            found[t.account_id].append(
                Payout(t.transaction_id, t.account_id, t.trade_date, t.type, -t.amount, t.description)
            )
    return found


def _wages(root: Path) -> set[str]:
    """Who has a 2025 Form W-2 on file: a 401(k)'s required beginning date may wait for their retirement."""
    documents = read_json(root, DOCUMENTS_INDEX)["documents"]
    return {str(d["person_id"]) for d in documents if d["kind"] == W2 and str(d["valuation_date"]) == str(YEAR_END)}


def _refuse_joint_table(root: Path, rules: Rules, account_id: str, owner: Person, people: dict[str, Person]) -> None:
    """The Joint and Last Survivor table applies when the sole beneficiary is a spouse more than ten years
    younger (26 CFR 1.401(a)(9)-5(c)(2)); the rules table does not hold it."""
    primaries = [
        b
        for b in read_csv(root, BENEFICIARIES_CSV, BENEFICIARIES_COLUMNS)
        if b["account_id"] == account_id and b["designation"] == "primary"
    ]
    if len(primaries) != 1 or primaries[0]["relationship"] != "spouse" or primaries[0]["person_id"] not in people:
        return
    spouse = people[primaries[0]["person_id"]]
    if spouse.born.year - owner.born.year > int(rules.value("joint_table_spouse_years")):
        raise UnsettledRmdError(
            f"{account_id}: the sole beneficiary is a spouse more than ten years younger, so the Joint and Last "
            "Survivor table applies, which this key does not hold"
        )


def _window(rules: Rules, born: date) -> date:
    """The last day a payout counts toward the 2025 RMD: the required beginning date in the first
    distribution year, otherwise 31 December 2025."""
    return required_beginning(rules, born) if first_distribution_year(rules, born) == YEAR else YEAR_END


def _inherited_period(rules: Rules, beneficiary: Person, decedent_born: date, died: date) -> tuple[int, Decimal]:
    """The distribution period after a death on or after the required beginning date: the longer of the
    beneficiary's single life expectancy, set in the year after the death and less one a year, and the
    decedent's remaining single life expectancy at the age in the year of death, less one a year
    (26 CFR 1.401(a)(9)-5(d)(1)(ii) and (iii))."""
    first = died.year + 1
    beneficiary_age = first - beneficiary.born.year
    beneficiary_period = rules.factor(SINGLE_LIFE, beneficiary_age) - (YEAR - first)
    decedent_age = died.year - decedent_born.year
    decedent_period = rules.factor(SINGLE_LIFE, decedent_age) - (YEAR - died.year)
    if beneficiary_period >= decedent_period:
        return beneficiary_age, beneficiary_period
    return decedent_age, decedent_period


def _inherited_figures(rules: Rules, beneficiary: Person, decedent_born: date, died: date) -> list[Decimal]:
    first = died.year + 1
    ages = (first - beneficiary.born.year, died.year - decedent_born.year)
    starts = [rules.factor(SINGLE_LIFE, a) for a in ages]
    return [
        *(Decimal(a) for a in ages),
        *starts,
        starts[0] - (YEAR - first),
        starts[1] - (YEAR - died.year),
        Decimal(YEAR - first),
        Decimal(YEAR - died.year),
    ]


def _inherited(
    rules: Rules, account: dict[str, str], beneficiary: Person, balance: Decimal, payouts: list[Payout]
) -> tuple[AccountRmd | None, list[Decimal]]:
    account_id = account["account_id"]
    if not (account["decedent_born"] and account["decedent_died"]):
        raise UnsettledRmdError(f"{account_id}: an inherited IRA with no decedent's dates")
    decedent_born = date.fromisoformat(account["decedent_born"])
    died = date.fromisoformat(account["decedent_died"])
    if not died.year < YEAR < died.year + int(rules.value("inherited_ira_years")):
        raise UnsettledRmdError(f"{account_id}: {YEAR} is not one of years 1 to 9 after the death on {died}")
    younger_by = int(rules.value("eligible_beneficiary_years"))
    gap_ok = (beneficiary.born.year - younger_by, beneficiary.born.month, beneficiary.born.day) > (
        decedent_born.year,
        decedent_born.month,
        decedent_born.day,
    )
    if not gap_ok or died.year - beneficiary.born.year < int(rules.value("age_of_majority")):
        raise UnsettledRmdError(
            f"{account_id}: {beneficiary.name} may be an eligible designated beneficiary, outside the ten-year rule"
        )
    if died < required_beginning(rules, decedent_born):
        # Death before the required beginning date: the account must be emptied by the tenth year's end,
        # with no annual distributions before it.
        return None, []
    if int(rules.value("annual_rmd_enforced_from")) > YEAR:
        return None, []
    age, period = _inherited_period(rules, beneficiary, decedent_born, died)
    paid = tuple(p for p in payouts if YEAR_START <= p.day <= YEAR_END)
    rmd = AccountRmd(
        account_id,
        INHERITED_IRA,
        beneficiary.person_id,
        balance,
        age,
        period,
        cents(balance / period),
        YEAR_END,
        paid,
        inherited_from=f"{account['decedent']} {decedent_born} {died}",
    )
    return rmd, _inherited_figures(rules, beneficiary, decedent_born, died)


def _parts(root: Path, account_ids: set[str]) -> list[KeyFigure]:
    """Each retirement account's positions, cash and value on every date the files cover: an answer that
    checks another date works these out."""
    positions: dict[tuple[str, date], Decimal] = defaultdict(lambda: ZERO)
    for row in read_positions(root):
        positions[(row.account_id, row.valuation_date)] += row.market_value
    figures: list[KeyFigure] = []
    for row in read_cash(root):
        if row.account_id in account_ids:
            held = positions[(row.account_id, row.valuation_date)]
            cash = row.settled_cash + row.unsettled_cash
            day = row.valuation_date
            figures += [
                KeyFigure(f"{row.account_id} positions value at {day}", held),
                KeyFigure(f"{row.account_id} value at {day}", held + cash),
            ]
    return figures


def _requirement_figures(r: Requirement, accounts: list[AccountRmd]) -> list[KeyFigure]:
    name = " + ".join(r.account_ids)
    figures = [
        KeyFigure(f"{name} {YEAR} RMD", r.rmd),
        KeyFigure(f"{name} paid toward the {YEAR} RMD by {r.deadline}", r.taken),
        KeyFigure(f"{name} shortfall", r.shortfall),
        KeyFigure(f"{name} paid beyond the RMD", max(r.taken - r.rmd, ZERO)),
        KeyFigure(f"{name} balances added up", sum((a.balance for a in accounts), ZERO)),
    ]
    figures += [KeyFigure(f"{name} excise tax at {fmt(rate)}", cents(r.shortfall * rate)) for rate in EXCISE_RATES]
    return figures


def household_rmd(household_root: Path, rules: Rules | None = None) -> HouseholdRmd:
    rules = rules or load_rules(YEAR)
    root = household_root
    household_id = str(read_json(root, PORTFOLIO_HOUSEHOLD)["household_id"])
    people, owners = _people(root), _owners(root)
    held, cash = _balances(root, PRIOR_YEAR_END)
    next_held, next_cash = _balances(root, YEAR_END)
    payouts = _payouts(root)
    working = _wages(root)
    accounts: list[AccountRmd] = []
    table: list[Decimal] = []
    retirement: set[str] = set()
    for account in read_csv(root, ACCOUNTS_CSV, ACCOUNTS_COLUMNS):
        account_id, kind = account["account_id"], account["account_type"]
        if kind not in (TRADITIONAL_IRA, PLAN, INHERITED_IRA):
            continue
        retirement.add(account_id)
        holders = owners.get(account_id, ())
        if len(holders) != 1 or holders[0] not in people:
            raise UnsettledRmdError(f"{account_id}: a retirement account has one owner, not {list(holders)}")
        owner = people[holders[0]]
        if account_id not in cash:
            raise UnsettledRmdError(f"{account_id} has no cash row on {PRIOR_YEAR_END}, so its balance is unknown")
        balance = held.get(account_id, ZERO) + cash[account_id]
        if kind == INHERITED_IRA:
            found, extra = _inherited(rules, account, owner, balance, payouts[account_id])
            if found is not None:
                accounts.append(found)
                table += extra
            continue
        if first_distribution_year(rules, owner.born) > YEAR:
            continue
        if owner.died is not None and owner.died <= YEAR_END:
            raise UnsettledRmdError(
                f"{account_id}: {owner.name} died on {owner.died}; a year-of-death RMD is not this key's"
            )
        if kind == PLAN and owner.person_id in working:
            raise UnsettledRmdError(
                f"{account_id}: {owner.name} has {YEAR} wages, so the 401(k)'s required beginning date may wait for "
                "retirement"
            )
        _refuse_joint_table(root, rules, account_id, owner, people)
        age = YEAR - owner.born.year
        factor = rules.factor(UNIFORM, age)
        deadline = _window(rules, owner.born)
        paid = tuple(p for p in payouts[account_id] if YEAR_START <= p.day <= deadline)
        accounts.append(
            AccountRmd(account_id, kind, owner.person_id, balance, age, factor, cents(balance / factor), deadline, paid)
        )
        table += [Decimal(age), factor]

    requirements: list[Requirement] = []
    figures: list[KeyFigure] = []
    iras: dict[tuple[str, str, str], list[AccountRmd]] = defaultdict(list)
    for a in accounts:
        figures += [
            KeyFigure(f"{a.account_id} positions value at {PRIOR_YEAR_END}", held.get(a.account_id, ZERO)),
            KeyFigure(f"{a.account_id} balance at {PRIOR_YEAR_END}", a.balance),
            KeyFigure(f"{a.account_id} {YEAR} RMD", a.rmd),
            KeyFigure(f"{a.account_id} paid by {a.deadline}", a.taken),
        ]
        if a.account_id in next_cash:
            # The next year's RMD, which an answer advising what to do now may work out: the 31 December
            # 2025 balance over the next year's divisor.
            following = next_held.get(a.account_id, ZERO) + next_cash[a.account_id]
            divisor = a.divisor - 1 if a.account_type == INHERITED_IRA else rules.factor(UNIFORM, a.age + 1)
            figures.append(KeyFigure(f"{a.account_id} {YEAR + 1} RMD", cents(following / divisor)))
            table.append(divisor)
        if a.account_type == TRADITIONAL_IRA:
            iras[(a.owner_id, a.account_type, "")].append(a)
            continue
        if a.account_type == INHERITED_IRA:
            iras[(a.owner_id, a.account_type, a.inherited_from)].append(a)
            continue
        r = Requirement(a.owner_id, a.account_type, (a.account_id,), a.rmd, a.deadline, a.taken)
        requirements.append(r)
        figures += _requirement_figures(r, [a])
    # An owner's traditional IRAs are met together (26 CFR 1.408-8), and so are one beneficiary's inherited
    # IRAs from the same decedent (Pub. 590-B, "More than one IRA"); a 401(k) only by itself.
    for (owner_id, kind, _), owned in iras.items():
        r = Requirement(
            owner_id,
            kind,
            tuple(a.account_id for a in owned),
            sum((a.rmd for a in owned), ZERO),
            owned[0].deadline,
            sum((a.taken for a in owned), ZERO),
        )
        requirements.append(r)
        figures += _requirement_figures(r, owned)
    figures += _parts(root, retirement)
    figures += [KeyFigure("total shortfall", sum((r.shortfall for r in requirements), ZERO))]
    return HouseholdRmd(
        household_id=household_id,
        people=tuple(people.values()),
        accounts=tuple(accounts),
        requirements=tuple(sorted(requirements, key=lambda r: r.account_ids)),
        computed_figures=tuple(figures),
        table_figures=tuple(table),
    )
