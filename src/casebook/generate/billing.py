"""Advisory fees: the tiered schedule applied to each billing group's quarter-end value."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from casebook.model.household import FeeSchedule, Household
from casebook.model.money import cents

ZERO = Decimal(0)
QUARTERS_PER_YEAR = 4


def quarterly_fee(schedule: FeeSchedule, value: Decimal) -> Decimal:
    annual = ZERO
    lower = ZERO
    for tier in schedule.tiers:
        upper = value if tier.up_to is None else min(value, tier.up_to)
        if upper > lower:
            annual += (upper - lower) * tier.annual_rate
        if tier.up_to is None or value <= tier.up_to:
            break
        lower = tier.up_to
    return cents(annual / QUARTERS_PER_YEAR)


@dataclass(frozen=True)
class QuarterBilling:
    quarter_end: date
    fee_date: date
    account_values: dict[str, Decimal]
    group_fees: dict[str, Decimal]
    account_fees: dict[str, Decimal]


def bill_quarter(household: Household, quarter_end: date, fee_date: date, values: dict[str, Decimal]) -> QuarterBilling:
    group_fees: dict[str, Decimal] = {}
    account_fees: dict[str, Decimal] = {}
    for group in household.billing_groups:
        group_value = sum((values[a] for a in group.account_ids), ZERO)
        fee = quarterly_fee(household.fee_schedule, group_value)
        group_fees[group.billing_group_id] = fee
        shares = {a: cents(fee * values[a] / group_value) if group_value else ZERO for a in group.account_ids}
        largest = max(sorted(group.account_ids), key=lambda a: values[a])
        shares[largest] += fee - sum(shares.values(), ZERO)
        account_fees.update(shares)
    return QuarterBilling(quarter_end, fee_date, dict(values), group_fees, account_fees)
