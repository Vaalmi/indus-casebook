"""Archetype 6. Established RMD retiree: a charitable distribution evidenced only in the CRM.

The trap's custodian recorded a qualified charitable distribution as an ordinary required
distribution, so nothing in its records shows it was a QCD; the CRM's signed request and the
charity's acknowledgment do. The clean twin's custodian recorded it as a QCD.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from casebook.model.events import CharitableDistribution, Event, RequiredDistribution, transaction_id
from casebook.model.files import ACCOUNTS_CSV, CASH_CSV, CRM_JSON, POSITIONS_CSV, TRANSACTIONS_CSV
from casebook.model.household import CrmActivity, Household
from casebook.model.money import cents, usd
from casebook.model.registry import FigureTable, RegistryEntry
from casebook.plant.a05_first_rmd import (
    DISTRIBUTION_YEAR,
    IRA,
    UNIFORM,
    Payout,
    age_in,
    distributions_for,
    gross,
    half_birthday,
    prior_year_end_balance,
    refuse_joint_table,
    required_beginning_date,
)
from casebook.plant.common import PlantContext, PlantError, Planting
from casebook.rules import load_rules

ITEM_TYPE = "qcd_evidenced_in_crm_only"
ZERO = Decimal(0)
YEAR_END = date(DISTRIBUTION_YEAR, 12, 31)
# A QCD is made on or after the day the owner attains age 70½ (26 U.S.C. § 408(d)(8)(B)(ii)), an
# age the 2025 rules table does not hold.
QCD_AGE_YEARS = 70
# The CRM records that show a payment was a QCD.
QCD_REQUEST = "qcd_request"
ACKNOWLEDGMENT = "charity_acknowledgment"


@dataclass(frozen=True)
class QcdYear:
    """An IRA owner's QCD in the distribution year, its evidence, and the year's RMD it counts toward."""

    owner_id: str
    account_id: str
    qcd: CharitableDistribution
    half_birthday: date
    limit: Decimal
    request: CrmActivity
    acknowledgment: CrmActivity
    balance: Decimal
    age: int
    factor: Decimal
    rmd: Decimal
    paid: tuple[Payout, ...]

    @property
    def taken(self) -> Decimal:
        return gross(self.paid)

    @property
    def taxable(self) -> Decimal:
        return gross(tuple(p for p in self.paid if not isinstance(p, CharitableDistribution)))


def _evidence(hh: Household, kind: str, qcd: CharitableDistribution) -> CrmActivity:
    """The CRM record of `kind` that names the charity and the amount: a request before the payment,
    an acknowledgment after it."""
    amount = usd(-qcd.amount)
    for activity in hh.crm_activities:
        before = activity.day <= qcd.date if kind == QCD_REQUEST else activity.day >= qcd.date
        if activity.kind == kind and before and qcd.charity in activity.summary and amount in activity.summary:
            return activity
    raise PlantError(
        f"{hh.household_id}: the CRM holds no {kind.replace('_', ' ')} for {amount} to {qcd.charity} "
        f"{'by' if kind == QCD_REQUEST else 'after'} {qcd.date.isoformat()}"
    )


def _qcd_year(context: PlantContext) -> QcdYear:
    hh, rules = context.script.household, load_rules(DISTRIBUTION_YEAR)
    qcds = [e for e in context.events if isinstance(e, CharitableDistribution) and e.date.year == DISTRIBUTION_YEAR]
    if len(qcds) != 1:
        raise PlantError(f"{hh.household_id}: archetype 6 makes one QCD in {DISTRIBUTION_YEAR}, not {len(qcds)}")
    qcd = qcds[0]
    account = hh.account(qcd.account_id)
    owners = hh.owners(qcd.account_id)
    if account.account_type != IRA or len(owners) != 1:
        raise PlantError(f"{hh.household_id}: a QCD comes from one owner's traditional IRA, not {qcd.account_id}")
    owner = hh.person(owners[0])
    if required_beginning_date(rules, owner.born) > YEAR_END:
        raise PlantError(f"{hh.household_id}: {owner.name} is not yet past the required beginning date")
    aged = half_birthday(owner.born, QCD_AGE_YEARS)
    if qcd.date < aged:
        raise PlantError(f"{hh.household_id}: the QCD on {qcd.date} is before {owner.name} is 70½ on {aged}")
    limit = rules.value("qcd_limit")
    if -qcd.amount > limit:
        raise PlantError(f"{hh.household_id}: the QCD of {usd(-qcd.amount)} is above the {usd(limit)} limit")
    if [a.account_id for a in hh.accounts if a.account_type == IRA and hh.owners(a.account_id) == owners] != [
        qcd.account_id
    ]:
        raise PlantError(f"{hh.household_id}: archetype 6's owner has one traditional IRA")
    refuse_joint_table(hh, qcd.account_id, owner.born)
    balance = prior_year_end_balance(context, qcd.account_id)
    age = age_in(owner.born, DISTRIBUTION_YEAR)
    factor = rules.factor(UNIFORM, age)
    rmd = cents(balance / factor)
    paid = distributions_for(context, qcd.account_id, DISTRIBUTION_YEAR, YEAR_END)
    year = QcdYear(
        owner_id=owner.person_id,
        account_id=qcd.account_id,
        qcd=qcd,
        half_birthday=aged,
        limit=limit,
        request=_evidence(hh, QCD_REQUEST, qcd),
        acknowledgment=_evidence(hh, ACKNOWLEDGMENT, qcd),
        balance=balance,
        age=age,
        factor=factor,
        rmd=rmd,
        paid=paid,
    )
    if year.taken < rmd:
        raise PlantError(
            f"{hh.household_id}: {usd(year.taken)} paid toward the {DISTRIBUTION_YEAR} RMD of {usd(rmd)} by {YEAR_END}"
        )
    return year


def _table(year: QcdYear) -> FigureTable:
    rows: list[tuple[str, str]] = [
        (f"Balance of {year.account_id} on 2024-12-31", usd(year.balance)),
        (f"Uniform Lifetime factor, age {year.age}", str(year.factor)),
        (f"{DISTRIBUTION_YEAR} RMD", usd(year.rmd)),
    ]
    for paid in year.paid:
        what = "QCD" if isinstance(paid, CharitableDistribution) else "Distribution"
        rows.append((f"{what} on {paid.date.isoformat()} ({transaction_id(paid.event_id)})", usd(-paid.amount)))
    rows += [
        (f"Paid toward the {DISTRIBUTION_YEAR} RMD", usd(year.taken)),
        ("Excluded from income as a QCD", usd(-year.qcd.amount)),
        ("Taxable IRA distributions", usd(year.taxable)),
    ]
    return FigureTable(columns=("Working", "Amount"), rows=tuple(rows))


def _rmd_met(year: QcdYear) -> str:
    return (
        f"The QCD counts toward the {DISTRIBUTION_YEAR} required minimum distribution (26 U.S.C. § 408(d)(8)): the "
        f"RMD is the 31 December 2024 balance of {usd(year.balance)} divided by the Uniform Lifetime factor for age "
        f"{year.age}, {year.factor}, or {usd(year.rmd)}, and the QCD with the year's other distributions paid "
        f"{usd(year.taken)} by {YEAR_END.isoformat()}, so the RMD was met."
    )


def plant_trap(context: PlantContext) -> Planting:
    script = context.script
    assert script.planted is not None
    hh, spec = script.household, script.planted
    year = _qcd_year(context)
    qcd, owner = year.qcd, hh.person(year.owner_id)
    amount = usd(-qcd.amount)
    coded = RequiredDistribution(qcd.event_id, qcd.date, qcd.account_id, qcd.amount, DISTRIBUTION_YEAR, ZERO)
    recorded: tuple[Event, ...] = tuple(coded if e == qcd else e for e in context.events)
    conclusion = (
        f"On {qcd.date.isoformat()} {amount} left {owner.name}'s IRA {qcd.account_id} for {qcd.charity} "
        f"({transaction_id(qcd.event_id)}). The custodian's transactions record it as an ordinary required minimum "
        f"distribution for {DISTRIBUTION_YEAR} with nothing withheld, so nothing in its records shows it was a QCD, "
        f"and its Form 1099-R need not either: for {DISTRIBUTION_YEAR} the QCD code Y in box 7 is optional, and the "
        f"form reports the gross distribution. The CRM shows it was a qualified charitable distribution: "
        f"the QCD request "
        f"{owner.name} signed on {year.request.day.isoformat()} ({year.request.activity_id}) to pay the charity "
        f"directly, and the charity's acknowledgment letter logged on {year.acknowledgment.day.isoformat()} "
        f"({year.acknowledgment.activity_id}) confirming it received {amount} with no goods or services in return. "
        f"{owner.name} turned 70½ on {year.half_birthday.isoformat()}, before the payment, and {amount} is within the "
        f"{DISTRIBUTION_YEAR} limit of {usd(year.limit)}, so the distribution qualifies under 26 U.S.C. § 408(d)(8) "
        f"and {amount} is excluded from income. The taxable IRA distributions for {DISTRIBUTION_YEAR} are "
        f"{usd(year.taxable)}, not the {usd(year.taken)} the custodian's records show leaving the IRA as "
        f"distributions; the exclusion is claimed on the return, not on the custodian's form: on Form 1040, line 4a "
        f"shows {usd(year.taken)} and line 4b {usd(year.taxable)}, marked QCD. {_rmd_met(year)} The advisor should "
        "keep the request and the acknowledgment with the return, and ask the custodian to record the payment as a "
        "QCD so its records agree with the CRM's."
    )
    entry = RegistryEntry(
        item_id=spec.item_id,
        household_id=hh.household_id,
        kind="source_disagreement",
        item_type=spec.item_type,
        title="A QCD the custodian recorded as an ordinary distribution, shown as a QCD only in the CRM",
        sources=(TRANSACTIONS_CSV, CRM_JSON, ACCOUNTS_CSV, POSITIONS_CSV, CASH_CSV),
        conclusion=conclusion,
        figures=(
            ("QCD", amount),
            (f"QCD limit, {DISTRIBUTION_YEAR}", usd(year.limit)),
            (f"{DISTRIBUTION_YEAR} RMD", usd(year.rmd)),
            (f"Paid toward the {DISTRIBUTION_YEAR} RMD", usd(year.taken)),
            ("Excluded from income", amount),
            ("Taxable IRA distributions", usd(year.taxable)),
        ),
        table=_table(year),
        known_as_of=YEAR_END,
        references=(
            year.owner_id,
            year.account_id,
            transaction_id(qcd.event_id),
            year.request.activity_id,
            year.acknowledgment.activity_id,
        ),
    )
    return Planting(entries=(entry,), custodian_events=recorded)


def check_twin(context: PlantContext, kind: str) -> Planting:
    """Clean: the custodian coded the QCD as one (the event log is its record), the CRM agrees, the
    QCD is within the limit and after 70½, and the year's RMD was met."""
    if kind != "clean":
        raise PlantError(f"{context.script.household.household_id}: archetype 6's twin is clean, not {kind!r}")
    _qcd_year(context)
    return Planting()
