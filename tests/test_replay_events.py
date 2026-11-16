"""The seven whitelisted events slice 3 adds, each against a ledger worked out by hand."""

from datetime import date
from decimal import Decimal

import pytest

from casebook.model.dates import OPENING_DATE
from casebook.model.events import (
    WHITELISTED,
    CharitableDistribution,
    Death,
    Event,
    Opening,
    OpeningLot,
    RequiredDistribution,
    RothConversion,
    Split,
    Transfer,
    Vest,
    event_to_dict,
    parse_event,
)
from casebook.replay import ReplayError, Snapshot, replay

D = Decimal
IRA, ROTH, TAXABLE, OTHER = "SYN-00000001", "SYN-00000002", "SYN-00000003", "SYN-00000004"
DAY = date(2025, 6, 2)


def opening(account: str, cash: str, *lots: OpeningLot) -> Opening:
    return Opening(f"E-{account[-1]}", OPENING_DATE, account, lots, D(cash))


def lot(lot_id: str, units: int, cost: str, acquired: date = date(2020, 6, 1)) -> OpeningLot:
    return OpeningLot(lot_id, "SEC-0001", acquired, D(units), D(cost))


def after(*events: Event) -> Snapshot:
    return replay(list(events), [DAY]).snapshots[DAY]


def lots_of(snapshot: Snapshot, account: str) -> list[tuple[str, Decimal, Decimal, date]]:
    return sorted((x.lot_id, x.units, x.cost, x.acquired) for x in snapshot.lots if x.account_id == account)


def test_the_whitelist_is_the_thirteen_events_of_the_spec() -> None:
    assert sorted(WHITELISTED) == sorted(
        ["buy", "sell", "dividend", "contribution", "withdrawal", "rmd", "qcd", "roth_conversion", "transfer", "fee",
         "rsu_vest", "split", "death"]
    )  # fmt: skip


def test_an_rmd_takes_its_gross_from_ira_cash() -> None:
    # 10,000.00 less a 4,000.00 gross distribution (400.00 of it withheld) leaves 6,000.00.
    rmd = RequiredDistribution("E-9", DAY, IRA, D("-4000.00"), 2025, D("400.00"))
    assert after(opening(IRA, "10000.00"), rmd).settled_cash[IRA] == D("6000.00")


def test_a_qcd_takes_its_amount_from_ira_cash() -> None:
    qcd = CharitableDistribution("E-9", DAY, IRA, D("-2500.00"), "Riverside Food Bank")
    assert after(opening(IRA, "10000.00"), qcd).settled_cash[IRA] == D("7500.00")


def test_a_roth_conversion_moves_cash_from_the_traditional_ira_to_the_roth() -> None:
    conversion = RothConversion("E-9", DAY, IRA, ROTH, D("6000.00"))
    snapshot = after(opening(IRA, "10000.00"), opening(ROTH, "0.00"), conversion)
    assert (snapshot.settled_cash[IRA], snapshot.settled_cash[ROTH]) == (D("4000.00"), D("6000.00"))


def test_an_in_kind_transfer_moves_lots_with_their_dates_and_basis() -> None:
    # 120 of 150 units move, oldest first: all of L-1, and 20 of L-2's 50 (basis 900.00 x 20/50 = 360.00).
    source = opening(TAXABLE, "0.00", lot("L-1", 100, "1000.00"), lot("L-2", 50, "900.00", date(2022, 1, 10)))
    move = Transfer("E-9", DAY, TAXABLE, OTHER, "SEC-0001", D(120), D(0))
    snapshot = after(source, opening(OTHER, "0.00"), move)
    assert lots_of(snapshot, OTHER) == [
        ("L-1", D(100), D("1000.00"), date(2020, 6, 1)),
        ("L-2/E-9", D(20), D("360.00"), date(2022, 1, 10)),
    ]
    assert lots_of(snapshot, TAXABLE) == [("L-2", D(30), D("540.00"), date(2022, 1, 10))]


def test_a_cash_transfer_moves_cash() -> None:
    move = Transfer("E-9", DAY, TAXABLE, OTHER, None, D(0), D("500.00"))
    snapshot = after(opening(TAXABLE, "800.00"), opening(OTHER, "0.00"), move)
    assert (snapshot.settled_cash[TAXABLE], snapshot.settled_cash[OTHER]) == (D("300.00"), D("500.00"))


def test_an_rsu_vest_opens_a_lot_at_its_value_on_the_day() -> None:
    # 40 units at 125.50 is a basis of 5,020.00, acquired on the vesting date.
    vest = Vest("E-9", DAY, TAXABLE, "SEC-0001", D(40), D("125.50"))
    assert lots_of(after(opening(TAXABLE, "0.00"), vest), TAXABLE) == [("L-E-9", D(40), D("5020.00"), DAY)]


def test_a_three_for_two_split_adds_units_and_keeps_basis() -> None:
    split = Split("E-9", DAY, TAXABLE, "SEC-0001", 3, 2)
    events: list[Event] = [opening(TAXABLE, "0.00", lot("L-1", 100, "1000.00")), split]
    result = replay(events, [DAY])
    assert lots_of(result.snapshots[DAY], TAXABLE) == [("L-1", D(150), D("1000.00"), date(2020, 6, 1))]
    assert result.split_units == {"E-9": D(50)}


def test_a_death_steps_a_sole_owners_basis_up_to_the_value_on_the_day() -> None:
    # 100 units worth 30.00 on the day: basis 3,000.00, dated the day of death.
    death = Death("E-9", DAY, TAXABLE, "P-1", D(1), (("SEC-0001", D("30.00")),))
    snapshot = after(opening(TAXABLE, "0.00", lot("L-1", 100, "1000.00")), death)
    assert lots_of(snapshot, TAXABLE) == [("L-1", D(100), D("3000.00"), DAY)]


def test_a_death_steps_up_the_decedents_half_of_a_joint_account() -> None:
    # The stepped half: 50 units at 30.00 = 1,500.00, dated the day. The survivor's half keeps
    # half the old basis, 500.00, and the old date.
    death = Death("E-9", DAY, TAXABLE, "P-1", D("0.5"), (("SEC-0001", D("30.00")),))
    snapshot = after(opening(TAXABLE, "0.00", lot("L-1", 100, "1000.00")), death)
    assert lots_of(snapshot, TAXABLE) == [
        ("L-1", D(50), D("500.00"), date(2020, 6, 1)),
        ("L-1-S", D(50), D("1500.00"), DAY),
    ]


def test_a_death_with_no_value_for_a_holding_is_refused() -> None:
    death = Death("E-9", DAY, TAXABLE, "P-1", D(1), ())
    with pytest.raises(ReplayError, match="no value for SEC-0001"):
        after(opening(TAXABLE, "0.00", lot("L-1", 100, "1000.00")), death)


@pytest.mark.parametrize("share", ["0", "1.5"])
def test_a_step_up_share_outside_zero_to_one_is_refused(share: str) -> None:
    death = Death("E-9", DAY, TAXABLE, "P-1", D(share), (("SEC-0001", D("30.00")),))
    with pytest.raises(ReplayError, match="step-up share"):
        after(opening(TAXABLE, "0.00", lot("L-1", 100, "1000.00")), death)


def test_a_transfer_to_an_account_with_no_opening_lots_is_refused() -> None:
    move = Transfer("E-9", DAY, TAXABLE, OTHER, None, D(0), D("1.00"))
    with pytest.raises(ReplayError, match=f"{OTHER} has no opening lots"):
        after(opening(TAXABLE, "800.00"), move)


@pytest.mark.parametrize(
    "event",
    [
        RequiredDistribution("E-9", DAY, IRA, D("-4000.00"), 2025, D("400.00")),
        CharitableDistribution("E-9", DAY, IRA, D("-2500.00"), "Riverside Food Bank"),
        RothConversion("E-9", DAY, IRA, ROTH, D("6000.00")),
        Transfer("E-9", DAY, TAXABLE, OTHER, "SEC-0001", D(120), D(0)),
        Transfer("E-9", DAY, TAXABLE, OTHER, None, D(0), D("500.00")),
        Vest("E-9", DAY, TAXABLE, "SEC-0001", D(40), D("125.50")),
        Split("E-9", DAY, TAXABLE, "SEC-0001", 3, 2),
        Death("E-9", DAY, TAXABLE, "P-1", D("0.5"), (("SEC-0001", D("30.00")),)),
    ],
)
def test_each_new_event_round_trips_through_the_log(event: Event) -> None:
    assert parse_event(event_to_dict(event)) == event


def test_contributions_and_withdrawals_move_settled_cash() -> None:
    # 1,000.00 + 250.00 - 300.00 = 950.00.
    from casebook.model.events import Contribution, Withdrawal

    events: list[Event] = [
        opening(TAXABLE, "1000.00"),
        Contribution("E-8", date(2025, 3, 3), TAXABLE, D("250.00")),
        Withdrawal("E-9", DAY, TAXABLE, D("-300.00")),
    ]
    assert after(*events).settled_cash[TAXABLE] == D("950.00")
