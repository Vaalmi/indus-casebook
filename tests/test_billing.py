from datetime import date
from decimal import Decimal

import pytest

from casebook.generate.billing import bill_quarter, quarterly_fee
from casebook.model.household import (
    Account,
    BillingGroup,
    FeeSchedule,
    FeeTier,
    Household,
    TaxProfile,
)

D = Decimal
SCHEDULE = FeeSchedule(
    "FS-STD",
    "quarterly in arrears",
    (FeeTier(D(1_000_000), D("0.0100")), FeeTier(D(2_000_000), D("0.0080")), FeeTier(None, D("0.0060"))),
)


@pytest.mark.parametrize(
    ("value", "fee"),
    [
        # 1% of 800,000 is 8,000 a year, 2,000 a quarter.
        ("800000", "2000.00"),
        ("1000000", "2500.00"),
        # 10,000 on the first million plus 0.8% of 250,000 is 12,000 a year.
        ("1250000", "3000.00"),
        # 10,000 + 8,000 + 0.6% of 500,000 = 21,000 a year.
        ("2500000", "5250.00"),
        ("0", "0.00"),
    ],
)
def test_quarterly_fee_on_the_tiered_schedule(value: str, fee: str) -> None:
    assert quarterly_fee(SCHEDULE, D(value)) == D(fee)


def household(groups: tuple[BillingGroup, ...], accounts: tuple[str, ...]) -> Household:
    return Household(
        household_id="HH-0001",
        name="Test household",
        archetype=10,
        members=(),
        accounts=tuple(Account(a, "joint_taxable", "Joint", date(2020, 1, 1)) for a in accounts),
        ownership=(),
        tax_units=(),
        billing_groups=groups,
        disclosures=(),
        agreements=(),
        beneficiaries=(),
        fee_schedule=SCHEDULE,
        allocation=(),
        asset_classes={},
        restrictions=(),
        concentration_limit=D("0.20"),
        tax_profile=TaxProfile(date(2025, 4, 15), (), ()),
        configured=date(2020, 1, 1),
    )


def test_a_group_fee_is_shared_in_proportion_to_value() -> None:
    hh = household((BillingGroup("BG-1", "FS-STD", ("A", "B")),), ("A", "B"))
    billed = bill_quarter(hh, date(2025, 3, 31), date(2025, 4, 2), {"A": D(750_000), "B": D(500_000)})
    assert billed.group_fees == {"BG-1": D("3000.00")}
    assert billed.account_fees == {"A": D("1800.00"), "B": D("1200.00")}


def test_rounding_left_over_goes_to_the_largest_account() -> None:
    # 1,200,000 bills 11,600 a year, 2,900.00 a quarter; thirds round to 966.67 and
    # overshoot by a cent, which comes off the first of the tied accounts.
    hh = household((BillingGroup("BG-1", "FS-STD", ("A", "B", "C")),), ("A", "B", "C"))
    values = {"A": D(400_000), "B": D(400_000), "C": D(400_000)}
    billed = bill_quarter(hh, date(2025, 3, 31), date(2025, 4, 2), values)
    assert billed.account_fees == {"A": D("966.66"), "B": D("966.67"), "C": D("966.67")}
    assert sum(billed.account_fees.values()) == D("2900.00")
