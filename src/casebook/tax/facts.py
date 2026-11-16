"""Each tax unit's 2025 facts, from what happened: the household's script and its event log, replayed.

What a custodian recorded can be wrong (a planted RSU basis of zero, a QCD coded as a plain
distribution); the facts come from the true ledger, so the tax summary is the household's real
liability and the planted errors show only in the custodian's documents.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

from casebook.generate.script import HouseholdScript
from casebook.model.events import (
    Buy,
    CharitableDistribution,
    Contribution,
    Dividend,
    Event,
    RequiredDistribution,
    RothConversion,
    Vest,
    Withdrawal,
)
from casebook.model.household import Household
from casebook.model.money import cents
from casebook.model.tax import (
    EXEMPT,
    QUALIFIED,
    TAX_YEAR,
    Filer,
    IraFlows,
    TaxUnitFacts,
    age_for_the_year,
    dividend_character,
    long_term,
)
from casebook.replay import ClosedLot, ReplayResult, Snapshot
from casebook.securities.market import Market
from casebook.securities.master import Security

ZERO = Decimal(0)
YEAR_START, YEAR_END = date(TAX_YEAR, 1, 1), date(TAX_YEAR, 12, 31)
TAXABLE = ("joint_taxable", "individual_taxable")
IRA, PLAN, INHERITED = "traditional_ira", "401k", "inherited_ira"
WASH_SALE_DAYS = 30  # 26 U.S.C. § 1091(a): thirty days before or after the sale


def _in_year(day: date) -> bool:
    return YEAR_START <= day <= YEAR_END


def _account_value(snapshot: Snapshot, account_id: str, market: Market) -> Decimal:
    held = sum(
        (cents(units * market.price(sid, snapshot.day)) for sid, units in snapshot.holdings(account_id).items()),
        ZERO,
    )
    return held + snapshot.settled_cash[account_id] + snapshot.unsettled_cash[account_id]


class TaxFactsError(Exception):
    """A household the tax facts cannot state correctly."""


def disallowed_losses(closed: Sequence[ClosedLot], buys: Sequence[Buy | Vest], taxable: set[str]) -> dict[str, Decimal]:
    """The loss each 2025 loss sale in a taxable account may not deduct, by `event_id:lot_id` (26 U.S.C.
    § 1091(a)): shares of the same security bought in any of the tax unit's accounts within thirty days
    either side replace the shares sold. Each replacement share is matched once, to the loss lots in
    the order they were sold (Treas. Reg. § 1.1091-1(b), (c)); shares bought and then sold in the
    same sale replace nothing, and the rest of that purchase still does.

    A replacement bought in a taxable account takes the disallowed loss into its basis (§ 1091(d)),
    which the replayed lots do not hold, so such a household is refused rather than stated wrongly.
    The book's replacements are all bought in IRAs, where the loss is lost for good (Rev. Rul. 2008-5)."""
    window = timedelta(days=WASH_SALE_DAYS)
    sold_in: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    for lot in closed:
        sold_in[lot.event_id][lot.lot_id] += lot.units
    used: dict[str, Decimal] = defaultdict(lambda: ZERO)
    disallowed: dict[str, Decimal] = {}
    for lot in sorted(closed, key=lambda c: c.sold):  # stable: a sale's lots stay in the order it closed them
        if lot.account_id not in taxable or not _in_year(lot.sold) or lot.proceeds >= lot.cost:
            continue
        matched = ZERO
        for buy in sorted(buys, key=lambda b: b.date):
            if buy.security_id != lot.security_id or abs(buy.date - lot.sold) > window:
                continue
            kept = buy.units - sold_in[lot.event_id][f"L-{buy.event_id}"]
            take = min(kept - used[buy.event_id], lot.units - matched)
            if take <= 0:
                continue
            if buy.account_id in taxable:
                raise TaxFactsError(
                    f"{buy.event_id} replaces shares sold at a loss in {lot.event_id} inside a taxable account; "
                    "its basis would need the disallowed loss (26 U.S.C. § 1091(d))"
                )
            used[buy.event_id] += take
            matched += take
        if matched > 0:
            disallowed[f"{lot.event_id}:{lot.lot_id}"] = cents((lot.cost - lot.proceeds) * matched / lot.units)
    return disallowed


def tax_unit_facts(
    script: HouseholdScript,
    events: tuple[Event, ...],
    replayed: ReplayResult,
    market: Market,
    securities: dict[str, Security],
) -> list[TaxUnitFacts]:
    hh: Household = script.household
    owners = {o.account_id: o.owner_ids for o in hh.ownership}
    kind = {a.account_id: a.account_type for a in hh.accounts}
    year_end = replayed.snapshots[YEAR_END]
    profile = hh.tax_profile
    facts: list[TaxUnitFacts] = []
    for unit in hh.tax_units:
        people = set(unit.person_ids)
        # An account belongs to the tax unit of its first owner (a joint account's owners file together).
        accounts = {a for a, o in owners.items() if o and o[0] in people}
        taxable = {a for a in accounts if kind[a] in TAXABLE}
        dividends: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for e in events:
            if isinstance(e, Dividend) and e.account_id in taxable and _in_year(e.date):
                dividends[dividend_character(securities[e.security_id].alias)] += e.amount
        buys = [e for e in events if isinstance(e, Buy | Vest) and e.account_id in accounts]
        disallowed = disallowed_losses(replayed.closed, buys, taxable)
        short = long = ZERO
        for closed in replayed.closed:
            if closed.account_id not in taxable or not _in_year(closed.sold):
                continue
            gain = closed.proceeds - closed.cost + disallowed.get(f"{closed.event_id}:{closed.lot_id}", ZERO)
            if long_term(closed.acquired, closed.sold):
                long += gain
            else:
                short += gain
        carried = next((c for c in profile.loss_carryforwards if c.tax_unit_id == unit.tax_unit_id), None)
        basis = {b.person_id: b.basis for b in profile.ira_basis}
        iras: list[IraFlows] = []
        plan = inherited = withheld = ZERO
        for person in unit.person_ids:
            own_iras = {a for a in accounts if kind[a] == IRA and owners[a] == (person,)}
            contributions = distributions = conversions = qcd = ZERO
            for e in events:
                if not _in_year(e.date) or getattr(e, "account_id", None) not in own_iras:
                    continue
                match e:
                    case Contribution():
                        contributions += e.amount
                    case RequiredDistribution():
                        distributions += -e.amount
                        withheld += e.withheld
                    case Withdrawal():
                        distributions += -e.amount
                    case CharitableDistribution():
                        qcd += -e.amount
                    case RothConversion():
                        conversions += e.amount
                    case _:
                        pass
            if own_iras or basis.get(person, ZERO):
                iras.append(
                    IraFlows(
                        person_id=person,
                        basis_prior=basis.get(person, ZERO),
                        nondeductible_contributions=contributions,
                        distributions=distributions,
                        conversions=conversions,
                        qcd=qcd,
                        year_end_value=sum((_account_value(year_end, a, market) for a in sorted(own_iras)), ZERO),
                    )
                )
        for e in events:
            account = getattr(e, "account_id", None)
            if account not in accounts or not _in_year(e.date) or kind[account] not in (PLAN, INHERITED):
                continue
            if isinstance(e, RequiredDistribution | Withdrawal):
                if kind[account] == PLAN:
                    plan += -e.amount
                else:
                    inherited += -e.amount
                if isinstance(e, RequiredDistribution):
                    withheld += e.withheld
        filers = tuple(
            Filer(
                person_id=p,
                age=age_for_the_year(hh.person(p).born, hh.person(p).died),
                wages=sum(
                    (i.amount for i in hh.income if i.person_id == p and i.kind == "wages" and i.year == TAX_YEAR), ZERO
                ),
                social_security=sum(
                    (
                        i.amount
                        for i in hh.income
                        if i.person_id == p and i.kind == "social_security" and i.year == TAX_YEAR
                    ),
                    ZERO,
                ),
            )
            for p in unit.person_ids
        )
        facts.append(
            TaxUnitFacts(
                household_id=hh.household_id,
                tax_unit_id=unit.tax_unit_id,
                filing_status=unit.filing_status,
                filers=filers,
                taxable_interest=ZERO,
                tax_exempt_interest=dividends[EXEMPT],
                ordinary_dividends=dividends[QUALIFIED] + dividends["ordinary"],
                qualified_dividends=dividends[QUALIFIED],
                short_term_gain=short,
                long_term_gain=long,
                carryforward_short=carried.short_term if carried else ZERO,
                carryforward_long=carried.long_term if carried else ZERO,
                iras=tuple(iras),
                plan_distributions=plan,
                inherited_ira_distributions=inherited,
                federal_withholding=withheld,
            )
        )
    return facts
