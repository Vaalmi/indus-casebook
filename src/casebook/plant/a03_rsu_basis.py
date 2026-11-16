"""Archetype 3. Concentrated executive: RSU basis missing in the custodian's records; the IPS concentration limit.

The trap's custodian books each RSU release at no cost, so its tax lots and realized lots (the
source of its 1099-B) show zero basis, while the employer's release confirmations in the CRM give
each release's value, which was taxed as wages and is the shares' basis. The clean twin's
custodian books the release value, and its employer stock is within the IPS limit.
"""

import dataclasses
from dataclasses import dataclass
from decimal import Decimal

from casebook.model.dates import SCENARIO_DATE
from casebook.model.events import Event, Vest, lot_id, transaction_id
from casebook.model.files import (
    CRM_JSON,
    PORTFOLIO_IPS,
    POSITIONS_CSV,
    REALIZED_CSV,
    TAX_LOTS_CSV,
    TRANSACTIONS_CSV,
)
from casebook.model.household import CrmActivity, Household
from casebook.model.money import cents, fmt, usd
from casebook.model.registry import FigureTable, RegistryEntry
from casebook.plant.common import PlantContext, PlantError, Planting, account_value, names
from casebook.replay import ClosedLot, replay
from casebook.securities.master import by_id, load_master

ITEM_TYPE = "rsu_basis_missing"
ZERO = Decimal(0)
RELEASE_CONFIRMATION = "rsu_release_confirmation"
WAGES = "wages"


@dataclass(frozen=True)
class _Releases:
    vests: tuple[Vest, ...]
    security_id: str
    employer: str
    confirmations: tuple[CrmActivity, ...]
    value: Decimal


def _confirmation(hh: Household, vest: Vest) -> CrmActivity | None:
    """The CRM's record of a release: its date, shares and value, as the employer confirmed them."""
    value = usd(cents(vest.units * vest.price))
    for activity in hh.crm_activities:
        text = activity.summary
        if (
            activity.kind == RELEASE_CONFIRMATION
            and activity.day >= vest.date
            and vest.date.isoformat() in text
            and f"{fmt(vest.units)} restricted stock units" in text
            and value in text
        ):
            return activity
    return None


def _releases(context: PlantContext) -> _Releases:
    """The household's RSU releases, each confirmed in the CRM, and the wages that include them."""
    hh = context.script.household
    vests = tuple(e for e in context.events if isinstance(e, Vest))
    if not vests:
        raise PlantError(f"{hh.household_id}: no RSU vests in the event log")
    held = {v.security_id for v in vests}
    if len(held) != 1:
        raise PlantError(f"{hh.household_id}: RSUs vest in {len(held)} securities, not one employer's stock")
    security_id = vests[0].security_id
    # The household's records name the employer by its alias; the conclusion names it as the build does.
    alias = by_id(load_master())[security_id].alias
    employer = context.label(security_id)
    confirmations: list[CrmActivity] = []
    for vest in vests:
        found = _confirmation(hh, vest)
        if found is None:
            raise PlantError(
                f"{hh.household_id}: no release confirmation in the CRM gives the {fmt(vest.units)} shares and "
                f"{usd(cents(vest.units * vest.price))} released on {vest.date}"
            )
        confirmations.append(found)
    value = sum((cents(v.units * v.price) for v in vests), ZERO)
    owners = {p for v in vests for p in hh.owners(v.account_id)}
    years = {v.date.year for v in vests}
    wages = sum(
        (i.amount for i in hh.income if i.person_id in owners and i.kind == WAGES and i.payer == alias),
        ZERO,
    )
    if len(years) != 1 or wages < value:
        raise PlantError(
            f"{hh.household_id}: the wages from {employer} ({usd(wages)}) do not include the "
            f"{usd(value)} of RSU releases"
        )
    return _Releases(vests, security_id, employer, tuple(confirmations), value)


def _concentration(context: PlantContext, security_id: str) -> tuple[Decimal, Decimal]:
    """The employer stock's value across the household on the scenario date, and the household's total."""
    snapshot = context.snapshot(SCENARIO_DATE)
    price = context.market.price(security_id, SCENARIO_DATE)
    accounts = [a.account_id for a in context.script.household.accounts]
    held = sum((cents(snapshot.units(a, security_id) * price) for a in accounts), ZERO)
    total = sum((account_value(snapshot, a, context.market) for a in accounts), ZERO)
    return held, total


def _percent(share: Decimal) -> str:
    return f"{cents(share * 100)}%"


def _sold(context: PlantContext, releases: _Releases) -> list[ClosedLot]:
    lots = {lot_id(v.event_id) for v in releases.vests}
    return [c for c in context.replayed.closed if c.lot_id in lots]


def plant_trap(context: PlantContext) -> Planting:
    script = context.script
    assert script.planted is not None
    hh, spec = script.household, script.planted
    releases = _releases(context)
    sold = _sold(context, releases)
    if not sold:
        raise PlantError(f"{spec.item_id}: no released shares are sold, so the custodian overstates no gain")
    held, total = _concentration(context, releases.security_id)
    limit = hh.concentration_limit
    if held / total <= limit:
        raise PlantError(
            f"{spec.item_id}: {releases.employer} is {_percent(held / total)} of the household on {SCENARIO_DATE}, "
            f"not above the IPS concentration limit of {_percent(limit)}"
        )
    # The custodian booked every release at no cost: the same events, the vesting price left at zero.
    vest_ids = {v.event_id for v in releases.vests}
    recorded: tuple[Event, ...] = tuple(
        dataclasses.replace(e, price=ZERO) if isinstance(e, Vest) and e.event_id in vest_ids else e
        for e in context.events
    )
    custodian = replay(recorded, tuple(context.replayed.snapshots))
    shown = {(c.event_id, c.lot_id): c.cost for c in custodian.closed}
    vested_on = {lot_id(v.event_id): v.date for v in releases.vests}
    rows: list[tuple[str, ...]] = []
    units = true_basis = shown_basis = proceeds = ZERO
    for lot in sold:
        custodian_cost = shown[(lot.event_id, lot.lot_id)]
        rows.append(
            (
                lot.lot_id,
                vested_on[lot.lot_id].isoformat(),
                lot.sold.isoformat(),
                fmt(lot.units),
                usd(lot.proceeds),
                usd(custodian_cost),
                usd(lot.cost),
                usd(lot.proceeds - custodian_cost),
                usd(lot.proceeds - lot.cost),
            )
        )
        units += lot.units
        true_basis += lot.cost
        shown_basis += custodian_cost
        proceeds += lot.proceeds
    overstated = true_basis - shown_basis
    still_held = [lot for lot in context.snapshot(SCENARIO_DATE).lots if lot.lot_id in vested_on and lot.units > 0]
    missing = sum((lot.cost for lot in still_held), ZERO)
    held_units = sum((lot.units for lot in still_held), ZERO)
    sales = sorted({lot.event_id for lot in sold})
    sale_days = sorted({lot.sold for lot in sold})
    person = names(hh, tuple(sorted({p for v in releases.vests for p in hh.owners(v.account_id)})))
    accounts = sorted({v.account_id for v in releases.vests})
    conclusion = (
        f"{person}'s employer, {releases.employer} ({releases.security_id}), released "
        f"{fmt(sum((v.units for v in releases.vests), ZERO))} shares into {', '.join(accounts)} at "
        f"{len(releases.vests)} vestings from {releases.vests[0].date.isoformat()} to "
        f"{releases.vests[-1].date.isoformat()}, worth {usd(releases.value)} on the days they vested. The "
        f"release confirmations in the CRM ({', '.join(c.activity_id for c in releases.confirmations)}) give each "
        "vesting's shares and value, and the value is included in the 2025 wages, so it is the shares' basis "
        "(IRC § 83(a); Treas. Reg. § 1.83-4(b)(1)). The custodian booked every vesting at no cost: its tax lots "
        f"show $0.00 basis, and its realized lots for the sale of {fmt(units)} released shares on "
        f"{', '.join(d.isoformat() for d in sale_days)} show basis of {usd(shown_basis)} and a gain of "
        f"{usd(proceeds - shown_basis)}. Their true basis is {usd(true_basis)}, so the custodian's figures, and a "
        f"1099-B built from them, overstate the 2025 gain by {usd(overstated)}; the true gain is "
        f"{usd(proceeds - true_basis)}, short-term. The sale should be reported on Form 8949 with the basis "
        f"corrected (code B, the adjustment in column (g)), and the custodian asked to correct its lots: the "
        f"{fmt(held_units)} released shares still held also show no basis, against a true basis of "
        f"{usd(missing)}. Separately, {releases.employer} is {_percent(held / total)} of the household "
        f"({usd(held)} of {usd(total)}) on {SCENARIO_DATE.isoformat()}, above the IPS concentration limit of "
        f"{_percent(limit)}."
    )
    entry = RegistryEntry(
        item_id=spec.item_id,
        household_id=hh.household_id,
        kind="source_disagreement",
        item_type=spec.item_type,
        title="RSU basis missing: the custodian books released shares at no cost",
        sources=(TAX_LOTS_CSV, REALIZED_CSV, TRANSACTIONS_CSV, CRM_JSON, POSITIONS_CSV, PORTFOLIO_IPS),
        conclusion=conclusion,
        figures=(
            ("Released shares sold", fmt(units)),
            ("Basis the custodian shows", usd(shown_basis)),
            ("True basis", usd(true_basis)),
            ("Gain overstated", usd(overstated)),
            ("Basis missing on released shares still held", usd(missing)),
            (f"{releases.employer}, share of the household on {SCENARIO_DATE.isoformat()}", _percent(held / total)),
            ("IPS concentration limit", _percent(limit)),
        ),
        table=FigureTable(
            columns=(
                "Lot",
                "Vested on",
                "Sold on",
                "Shares",
                "Proceeds",
                "Basis the custodian shows",
                "True basis",
                "Gain the custodian shows",
                "True gain",
            ),
            rows=tuple(rows),
        ),
        known_as_of=SCENARIO_DATE,
        references=(
            *accounts,
            releases.security_id,
            *(transaction_id(v.event_id) for v in releases.vests),
            *(transaction_id(s) for s in sales),
            *sorted(vested_on),
            *(c.activity_id for c in releases.confirmations),
        ),
        # The employer stock above the IPS limit is part of the situation, named with the security.
        crosses=("concentration",),
    )
    return Planting(entries=(entry,), custodian_events=recorded)


def check_twin(context: PlantContext, kind: str) -> Planting:
    """A clean twin has the same releases and sale; the custodian books each release's value, within the limit."""
    hh = context.script.household
    if kind != "clean":
        raise PlantError(f"{hh.household_id}: archetype 3's twin is clean, not {kind}")
    releases = _releases(context)
    snapshot = context.snapshot(SCENARIO_DATE)
    for vest in releases.vests:
        lot = lot_id(vest.event_id)
        booked = sum((c.cost for c in context.replayed.closed if c.lot_id == lot), ZERO)
        booked += sum((x.cost for x in snapshot.lots if x.lot_id == lot), ZERO)
        if booked != cents(vest.units * vest.price):
            raise PlantError(
                f"{hh.household_id}: lot {lot} carries basis {usd(booked)}, not the release value "
                f"{usd(cents(vest.units * vest.price))}"
            )
    held, total = _concentration(context, releases.security_id)
    if held / total > hh.concentration_limit:
        raise PlantError(
            f"{hh.household_id}: a clean twin's {releases.employer} is {_percent(held / total)} of the household, "
            f"above the IPS concentration limit of {_percent(hh.concentration_limit)}"
        )
    return Planting()
