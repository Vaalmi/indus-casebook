"""Archetype 10, fee and IPS drift: a signed householding agreement the billing ignores, so the
household misses the schedule's breakpoint. The near-miss twin has the same shape and no agreement."""

from decimal import Decimal

from casebook.generate.billing import quarterly_fee
from casebook.model.files import CRM_JSON, PORTFOLIO_BILLING, PORTFOLIO_HOUSEHOLD, TRANSACTIONS_CSV
from casebook.model.household import Household
from casebook.model.money import usd
from casebook.model.registry import FigureTable, RegistryEntry
from casebook.plant.common import PlantContext, PlantError, Planting, names

ITEM_TYPE = "missed_fee_breakpoint"
ZERO = Decimal(0)


def _groups_of(household: Household, account_ids: tuple[str, ...]) -> list[str]:
    return sorted({g.billing_group_id for g in household.billing_groups for a in account_ids if a in g.account_ids})


def _first_bound(household: Household) -> Decimal:
    bound = household.fee_schedule.tiers[0].up_to
    if bound is None:
        raise PlantError(f"{household.household_id}: a flat fee schedule has no breakpoint to miss")
    return bound


def plant_trap(context: PlantContext) -> Planting:
    script, quarters = context.script, context.quarters
    assert script.planted is not None
    hh = script.household
    spec = script.planted
    agreement = next((a for a in hh.agreements if a.agreement_id == spec.details["agreement_id"]), None)
    if agreement is None or agreement.kind != "householding":
        raise PlantError(
            f"{spec.item_id}: {spec.details['agreement_id']} is not a householding agreement of {hh.household_id}"
        )
    groups = _groups_of(hh, agreement.account_ids)
    if len(groups) < 2:
        raise PlantError(
            f"{spec.item_id}: the agreement's accounts already bill as one group, so no breakpoint is missed"
        )
    rows: list[tuple[str, ...]] = []
    billed_total = implied_total = ZERO
    for quarter in quarters:
        combined = sum((quarter.account_values[a] for a in agreement.account_ids), ZERO)
        billed = sum((quarter.account_fees[a] for a in agreement.account_ids), ZERO)
        implied = quarterly_fee(hh.fee_schedule, combined)
        if billed <= implied:
            raise PlantError(
                f"{spec.item_id}: in the quarter to {quarter.quarter_end} the fee debited is not above the agreed fee"
            )
        billed_total += billed
        implied_total += implied
        rows.append(
            (
                quarter.quarter_end.isoformat(),
                quarter.fee_date.isoformat(),
                usd(combined),
                usd(billed),
                usd(implied),
                usd(billed - implied),
            )
        )
    over = billed_total - implied_total
    bound = _first_bound(hh)
    conclusion = (
        f"The householding agreement {agreement.agreement_id}, signed on {agreement.signed.isoformat()} by "
        f"{names(hh, agreement.party_ids)}, puts accounts {', '.join(agreement.account_ids)} in one billing group. "
        f"The portfolio system still bills them as {len(groups)} groups ({', '.join(groups)}). Their combined "
        f"quarter-end value was above {usd(bound)} in each of the {len(quarters)} quarters billed from "
        f"{quarters[0].fee_date.isoformat()} to {quarters[-1].fee_date.isoformat()}, so the schedule's lower rates "
        f"above {usd(bound)} should have applied. The fees debited on these accounts total {usd(billed_total)}; "
        f"the agreement implies {usd(implied_total)}. The household was overbilled by {usd(over)}."
    )
    entry = RegistryEntry(
        item_id=spec.item_id,
        household_id=hh.household_id,
        kind="source_disagreement",
        item_type=spec.item_type,
        title="Missed fee breakpoint: a signed householding agreement is not applied in billing",
        sources=(CRM_JSON, PORTFOLIO_HOUSEHOLD, PORTFOLIO_BILLING, TRANSACTIONS_CSV),
        conclusion=conclusion,
        figures=(
            (f"Fees debited, {len(quarters)} quarters", usd(billed_total)),
            ("Fees under the agreement", usd(implied_total)),
            ("Overbilled", usd(over)),
        ),
        table=FigureTable(
            columns=(
                "Quarter end",
                "Fee debited on",
                "Combined value",
                "Fees debited",
                "Fees under the agreement",
                "Overbilled",
            ),
            rows=tuple(rows),
        ),
        known_as_of=quarters[-1].fee_date,
        references=(agreement.agreement_id, *agreement.account_ids),
    )
    return Planting(entries=(entry,))


def check_twin(context: PlantContext, kind: str) -> Planting:
    """A near miss looks like the trap: accounts above the breakpoint together, billed apart.

    What makes it a near miss is that no agreement joins them.
    """
    if kind != "near_miss":
        return Planting()
    hh, quarters = context.script.household, context.quarters
    if any(a.kind == "householding" for a in hh.agreements):
        raise PlantError(f"{hh.household_id}: a near miss has no householding agreement")
    if len(hh.billing_groups) < 2:
        raise PlantError(f"{hh.household_id}: a near miss bills its accounts in more than one group")
    bound = _first_bound(hh)
    for quarter in quarters:
        if sum(quarter.account_values.values(), ZERO) <= bound:
            raise PlantError(
                f"{hh.household_id}: in the quarter to {quarter.quarter_end} "
                f"the accounts together are not above {usd(bound)}"
            )
    return Planting()
