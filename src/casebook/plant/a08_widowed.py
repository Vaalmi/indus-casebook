"""Archetype 8. Recently widowed investor: the basis step-up lagging in the custodian's records; beneficiary updates.

A spouse dies holding a joint account with the survivor as joint tenants with right of
survivorship: half of each lot steps up to its value on the date of death. The trap's custodian
never books the step-up, and the survivor's IRA still names the dead spouse as its primary
beneficiary. The clean twin's custodian books it, and the survivor has named new beneficiaries.
"""

from dataclasses import dataclass
from decimal import Decimal

from casebook.model.dates import SCENARIO_DATE
from casebook.model.events import Death
from casebook.model.files import BENEFICIARIES_CSV, CRM_JSON, PORTFOLIO_HOUSEHOLD, TAX_LOTS_CSV, TRANSACTIONS_CSV
from casebook.model.household import Beneficiary, CrmActivity, Household, Person
from casebook.model.money import cents, fmt, usd
from casebook.model.registry import FigureTable, RegistryEntry
from casebook.plant.common import PlantContext, PlantError, Planting
from casebook.replay import replay

ITEM_TYPE = "step_up_lag"
ZERO = Decimal(0)
SPOUSES = ("primary", "spouse")
JOINT_TAXABLE = "joint_taxable"
SURVIVORSHIP = "Joint tenants with right of survivorship"
# IRC § 2040(b): half of a qualified joint interest of spouses is included in the first to die's estate.
QUALIFIED_JOINT_SHARE = Decimal("0.5")
IRA_TYPES = ("traditional_ira", "roth_ira")
DEATH_NOTIFICATION = "death_notification"
CUSTODIAN_REQUEST = "custodian_request"


@dataclass(frozen=True)
class _Death:
    death: Death
    decedent: Person
    survivor: Person
    # The CRM's records of it: the death notification and the request for date-of-death values.
    records: tuple[CrmActivity, ...]


def _record(hh: Household, kind: str, death: Death) -> CrmActivity:
    for activity in sorted(hh.crm_activities, key=lambda a: (a.day, a.activity_id)):
        if activity.kind == kind and activity.day >= death.date and hh.person(death.person_id).name in activity.summary:
            return activity
    raise PlantError(
        f"{hh.household_id}: no {kind.replace('_', ' ')} in the CRM names {hh.person(death.person_id).name}"
    )


def _the_death(context: PlantContext) -> _Death:
    """One spouse's death, stepping up half of each lot in a joint account with right of survivorship."""
    hh = context.script.household
    deaths = [e for e in context.events if isinstance(e, Death)]
    if len(deaths) != 1:
        raise PlantError(f"{hh.household_id}: {len(deaths)} deaths in the event log, not one")
    death = deaths[0]
    account = hh.account(death.account_id)
    owners = hh.owners(death.account_id)
    decedent = hh.person(death.person_id)
    others = [hh.person(p) for p in owners if p != death.person_id]
    if (
        account.account_type != JOINT_TAXABLE
        or account.registration != SURVIVORSHIP
        or len(owners) != 2
        or len(others) != 1
        or {decedent.relationship, others[0].relationship} != set(SPOUSES)
    ):
        raise PlantError(
            f"{hh.household_id}: {death.account_id} is not held by two spouses as joint tenants with right of "
            "survivorship"
        )
    if death.share != QUALIFIED_JOINT_SHARE:
        raise PlantError(
            f"{hh.household_id}: the death steps up {fmt(death.share)} of each lot, not the decedent's half "
            "of a qualified joint interest"
        )
    records = (_record(hh, DEATH_NOTIFICATION, death), _record(hh, CUSTODIAN_REQUEST, death))
    return _Death(death, decedent, others[0], records)


def _iras(hh: Household, person_id: str) -> list[str]:
    return [
        a.account_id for a in hh.accounts if a.account_type in IRA_TYPES and hh.owners(a.account_id) == (person_id,)
    ]


def _naming(hh: Household, decedent: Person) -> list[Beneficiary]:
    return [b for b in hh.beneficiaries if b.person_id == decedent.person_id or b.name == decedent.name]


def plant_trap(context: PlantContext) -> Planting:
    script = context.script
    assert script.planted is not None
    hh, spec = script.household, script.planted
    found = _the_death(context)
    death, decedent, survivor = found.death, found.decedent, found.survivor
    stale = [
        b for b in _naming(hh, decedent) if b.designation == "primary" and b.account_id in _iras(hh, survivor.person_id)
    ]
    if not stale:
        raise PlantError(
            f"{spec.item_id}: no IRA of {survivor.name}'s still names {decedent.name} as primary beneficiary"
        )
    # The custodian never booked the step-up: the event log without the death.
    recorded = tuple(e for e in context.events if e.event_id != death.event_id)
    custodian = replay(recorded, tuple(context.replayed.snapshots)).snapshots[SCENARIO_DATE]
    actual = context.snapshot(SCENARIO_DATE)
    prices = dict(death.prices)
    rows: list[tuple[str, ...]] = []
    shown_total = correct_total = ZERO
    lots: list[str] = []
    for lot in sorted((x for x in custodian.lots if x.account_id == death.account_id), key=lambda x: x.lot_id):
        parts = [x for x in actual.lots if x.lot_id in (lot.lot_id, f"{lot.lot_id}-S")]
        if sum((x.units for x in parts), ZERO) != lot.units:
            raise PlantError(f"{spec.item_id}: lot {lot.lot_id} changes after the death, so its step-up is not shown")
        correct = sum((x.cost for x in parts), ZERO)
        value = cents(lot.units * prices[lot.security_id])
        rows.append(
            (
                lot.lot_id,
                lot.security_id,
                fmt(lot.units),
                usd(lot.cost),
                fmt(prices[lot.security_id]),
                usd(value),
                usd(correct),
                usd(correct - lot.cost),
            )
        )
        lots.append(lot.lot_id)
        shown_total += lot.cost
        correct_total += correct
    understated = correct_total - shown_total
    down = [r[0] for r in rows if r[7].startswith("-")]
    on = death.date.isoformat()
    contingent = [
        b.name for b in hh.beneficiaries if b.account_id in {s.account_id for s in stale} and b.designation != "primary"
    ]
    stale_text = "; ".join(f"{s.account_id} (designated {s.designated.isoformat()})" for s in stale)
    conclusion = (
        f"{decedent.name} died on {on}; the CRM records the death notification ({found.records[0].activity_id}, "
        f"{found.records[0].day.isoformat()}) and the request to the custodian for date-of-death values and the "
        f"step-up ({found.records[1].activity_id}, {found.records[1].day.isoformat()}). {decedent.name} and "
        f"{survivor.name} held {death.account_id} as joint tenants with right of survivorship. Between spouses that "
        "is a qualified joint interest, so half of each lot is included in the decedent's estate (IRC § 2040(b)) "
        f"and that half takes its value on {on} as its basis (IRC § 1014(a)); in a common-law property state "
        f"{survivor.name}'s half keeps its cost. The custodian never booked the step-up: its tax lots on "
        f"{SCENARIO_DATE.isoformat()} still show the "
        f"original basis of {usd(shown_total)} for the {len(rows)} lots, and its transactions show no step-up. The "
        f"correct basis is {usd(correct_total)}, so the custodian understates it by {usd(understated)}"
        + (
            f" (lot {', '.join(down)} was worth less than its cost on {on}, so its stepped half steps down)"
            if down
            else ""
        )
        + f". Any sale from the account would show too large a gain until the custodian books the step-up from "
        f"the values on {on}. Separately, {survivor.name}'s IRA {stale_text} still names {decedent.name} as its "
        "primary beneficiary"
        + (
            f"; as {decedent.name} has died, the contingent beneficiaries ({', '.join(contingent)}) would take"
            if contingent
            else ""
        )
        + f". {survivor.name} should name new beneficiaries."
    )
    entry = RegistryEntry(
        item_id=spec.item_id,
        household_id=hh.household_id,
        kind="source_disagreement",
        item_type=spec.item_type,
        title="Basis step-up lagging: the custodian never booked a spouse's death; a stale beneficiary",
        sources=(TAX_LOTS_CSV, TRANSACTIONS_CSV, CRM_JSON, PORTFOLIO_HOUSEHOLD, BENEFICIARIES_CSV),
        conclusion=conclusion,
        figures=(
            ("Basis the custodian shows", usd(shown_total)),
            (f"Correct basis after the step-up on {on}", usd(correct_total)),
            ("Basis understated", usd(understated)),
            *((f"{s.account_id} primary beneficiary", f"{decedent.name}, died {on}") for s in stale),
        ),
        table=FigureTable(
            columns=(
                "Lot",
                "Security",
                "Units",
                "Basis the custodian shows",
                f"Price on {on}",
                f"Value on {on}",
                "Correct basis",
                "Understated by",
            ),
            rows=tuple(rows),
        ),
        known_as_of=SCENARIO_DATE,
        references=(
            death.account_id,
            *lots,
            decedent.person_id,
            *(s.account_id for s in stale),
            *(r.activity_id for r in found.records),
        ),
    )
    return Planting(entries=(entry,), custodian_events=recorded)


def check_twin(context: PlantContext, kind: str) -> Planting:
    """A clean twin has the same death; the custodian books the step-up, and no designation names the dead spouse."""
    hh = context.script.household
    if kind != "clean":
        raise PlantError(f"{hh.household_id}: archetype 8's twin is clean, not {kind}")
    found = _the_death(context)
    decedent, survivor, on = found.decedent, found.survivor, found.death.date
    stale = _naming(hh, decedent)
    if stale:
        raise PlantError(
            f"{hh.household_id}: {', '.join(sorted({b.account_id for b in stale}))} still names {decedent.name} "
            "as a beneficiary"
        )
    for account_id in _iras(hh, survivor.person_id):
        primary = [b for b in hh.beneficiaries if b.account_id == account_id and b.designation == "primary"]
        if not primary or any(b.designated < on for b in primary):
            raise PlantError(
                f"{hh.household_id}: {survivor.name}'s IRA {account_id} has no primary beneficiaries designated "
                f"since {on.isoformat()}"
            )
    return Planting()
