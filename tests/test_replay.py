from datetime import date
from decimal import Decimal

import pytest

from casebook.model.dates import OPENING_DATE
from casebook.model.events import (
    Buy,
    Dividend,
    Event,
    Fee,
    Opening,
    OpeningLot,
    Sell,
    UnsupportedEventError,
    event_to_dict,
    parse_event,
)
from casebook.replay import OpeningDateError, OversoldError, ReplayError, replay

D = Decimal
ACCOUNT = "SYN-00000001"


def opening(day: date = OPENING_DATE) -> Opening:
    lot = OpeningLot("L-1", "SEC-0001", date(2020, 6, 1), D(100), D("1000.00"))
    return Opening("E-1", day, ACCOUNT, (lot,), D("1000.00"))


def history() -> list[Event]:
    # Hand-worked: buy 50 at 12.00 (cost 600.00); sell 120 at 15.00 relieves FIFO,
    # all 100 opening units (cost 1,000.00) then 20 bought units (cost 240.00).
    return [
        opening(),
        Buy("E-2", date(2025, 2, 3), date(2025, 2, 4), ACCOUNT, "SEC-0001", D(50), D("12.00"), D("-600.00")),
        Dividend("E-3", date(2025, 2, 20), ACCOUNT, "SEC-0001", D(150), D("0.1000"), D("15.00")),
        Sell("E-4", date(2025, 3, 3), date(2025, 3, 4), ACCOUNT, "SEC-0001", D(120), D("15.00"), D("1800.00")),
        Fee("E-5", date(2025, 4, 2), ACCOUNT, D("-25.00"), date(2025, 3, 31), "BG-1"),
    ]


def test_replay_matches_the_hand_worked_ledger() -> None:
    result = replay(history(), [date(2025, 2, 3), date(2025, 3, 3), date(2025, 4, 2)])
    assert result.opening.units(ACCOUNT, "SEC-0001") == D(100)
    assert result.opening.settled_cash[ACCOUNT] == D("1000.00")

    trade_day = result.snapshots[date(2025, 2, 3)]
    assert trade_day.units(ACCOUNT, "SEC-0001") == D(150)
    assert trade_day.settled_cash[ACCOUNT] == D("1000.00")
    assert trade_day.unsettled_cash[ACCOUNT] == D("-600.00")

    sale_day = result.snapshots[date(2025, 3, 3)]
    assert sale_day.units(ACCOUNT, "SEC-0001") == D(30)
    assert [lot.cost for lot in sale_day.lots] == [D("360.00")]
    assert sale_day.settled_cash[ACCOUNT] == D("415.00")
    assert sale_day.unsettled_cash[ACCOUNT] == D("1800.00")

    assert result.snapshots[date(2025, 4, 2)].settled_cash[ACCOUNT] == D("2190.00")
    closed = [(c.lot_id, c.units, c.cost, c.proceeds) for c in result.closed]
    assert closed == [("L-1", D(100), D("1000.00"), D("1500.00")), ("L-E-2", D(20), D("240.00"), D("300.00"))]


@pytest.mark.parametrize("day", [date(2024, 12, 31), date(2025, 2, 1)])
def test_opening_lots_must_be_dated_1_january_2025(day: date) -> None:
    with pytest.raises(OpeningDateError):
        replay([opening(day)], [])


def test_a_lot_cannot_be_oversold() -> None:
    sale = Sell("E-2", date(2025, 2, 3), date(2025, 2, 4), ACCOUNT, "SEC-0001", D(101), D("10.00"), D("1010.00"))
    with pytest.raises(OversoldError, match="sells 101"):
        replay([opening(), sale], [])


def test_events_out_of_order_are_refused() -> None:
    events = history()
    events[1], events[2] = events[2], events[1]
    with pytest.raises(ReplayError, match="earlier than"):
        replay(events, [])


def test_an_event_on_an_account_without_opening_lots_is_refused() -> None:
    fee = Fee("E-2", date(2025, 4, 2), "SYN-00000009", D("-1.00"), date(2025, 3, 31), "BG-1")
    with pytest.raises(ReplayError, match="no opening lots"):
        replay([opening(), fee], [])


def test_the_log_must_begin_with_opening_lots() -> None:
    with pytest.raises(ReplayError, match="begin with the opening lots"):
        replay(history()[1:], [])


def test_any_other_event_is_rejected_by_name() -> None:
    with pytest.raises(UnsupportedEventError, match="'merger'") as raised:
        parse_event({"type": "merger", "event_id": "E-9", "date": "2025-05-01", "account_id": ACCOUNT})
    assert raised.value.event_type == "merger"


def test_events_round_trip_through_the_log() -> None:
    for event in history():
        assert parse_event(event_to_dict(event)) == event
