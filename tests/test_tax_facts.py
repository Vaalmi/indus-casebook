"""Each tax unit's 2025 facts, as the book's sealed event logs hold them: what happened, not what the
custodian recorded. Expected figures are worked by hand from the events and the emitted files."""

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from casebook.model.events import Buy, Vest
from casebook.model.files import event_log_path, read_json
from casebook.model.tax import TaxUnitFacts, age_for_the_year, parse_facts
from casebook.replay import ClosedLot
from casebook.tax.facts import TaxFactsError, disallowed_losses

D = Decimal
TAXABLE, IRA = "SYN-1", "SYN-2"


def facts(book: Path, household: str) -> TaxUnitFacts:
    (unit,) = read_json(book, event_log_path(household))["tax_units"]
    return parse_facts(unit)


def test_released_rsu_shares_are_taxed_on_their_true_basis_not_the_custodians_zero(book: Path) -> None:
    """HH-3058 sold 1,600 shares on 2025-12-12 for $437,776.00: the February and May releases, 800 shares each
    at $216.06 and $229.90. True basis 172,848.00 + 183,920.00 = 356,768.00; short-term gain 81,008.00.
    The custodian booked both releases at no cost, so its 1099-B shows a gain of 437,776.00."""
    unit = facts(book, "HH-3058")
    assert (unit.short_term_gain, unit.long_term_gain) == (D("81008.00"), D(0))
    # Wages: 410,000 of salary and the four 2025 releases, 800 x (216.06 + 229.90 + 236.83 + 274.64).
    assert [(f.person_id, f.wages) for f in unit.filers] == [
        ("P-3058-1", D("1175944.00")),
        ("P-3058-2", D("138000.00")),
    ]


def test_a_qcd_the_custodian_miscoded_is_still_a_qcd_in_the_facts(book: Path) -> None:
    """HH-6047: Bernard's $12,000.00 QCD and his $9,659.73 RMD with $965.97 withheld; the custodian coded
    both as one ordinary distribution. Social Security 38,460 and 22,716; the muni fund's dividends are exempt."""
    unit = facts(book, "HH-6047")
    (ira,) = unit.iras
    assert (ira.person_id, ira.qcd, ira.distributions) == ("P-6047-1", D("12000.00"), D("9659.73"))
    assert unit.federal_withholding == D("965.97")
    assert [(f.age, f.social_security) for f in unit.filers] == [(78, D("38460.00")), (76, D("22716.00"))]
    assert unit.tax_exempt_interest > 0


def test_a_wash_sale_into_an_ira_disallows_the_replaced_share_of_the_loss(book: Path) -> None:
    """HH-9234 sold 847 shares at a loss of 53,516.17 on 2025-11-03 and bought 500 in Ingrid's IRA on
    2025-11-19. Disallowed 53,516.17 x 500 / 847 = 31,591.60; allowed 21,924.57, long-term (held since 2023)."""
    unit = facts(book, "HH-9234")
    assert (unit.short_term_gain, unit.long_term_gain) == (D(0), D("-21924.57"))


def year_end_value(book: Path, household: str, account: str) -> Decimal:
    root = book / "households" / household / "custodian"
    with (root / "positions.csv").open() as handle:
        held = sum(
            (
                D(p["market_value"])
                for p in csv.DictReader(handle)
                if p["account_id"] == account and p["valuation_date"] == "2025-12-31"
            ),
            D(0),
        )
    with (root / "cash.csv").open() as handle:
        cash = sum(
            (
                D(c["settled_cash"]) + D(c["unsettled_cash"])
                for c in csv.DictReader(handle)
                if c["account_id"] == account and c["valuation_date"] == "2025-12-31"
            ),
            D(0),
        )
    return held + cash


def test_a_backdoor_conversion_s_form_8606_inputs(book: Path) -> None:
    """HH-1204: Luka's $7,000.00 nondeductible contribution on 2025-02-10, converted on 2025-02-13. Line 6
    is all his traditional IRAs on the custodian's 2025-12-31 positions and cash: the emptied IRA (0.00) and
    the rollover IRA, 42,871.51 + 142,362.18 + 2,311.23 = 187,544.92, which makes most of the conversion taxable."""
    unit = facts(book, "HH-1204")
    (ira,) = unit.iras
    assert (ira.nondeductible_contributions, ira.conversions, ira.basis_prior) == (D("7000.00"), D("7000.00"), D(0))
    both = year_end_value(book, "HH-1204", "SYN-12040002") + year_end_value(book, "HH-1204", "SYN-12040003")
    assert ira.year_end_value == both == D("187544.92")


# The wash-sale matching, on hand-made lots.


def sold(lot_id: str, units: str, cost: str, proceeds: str, event_id: str = "E-S1", day: int = 10) -> ClosedLot:
    return ClosedLot(
        event_id, lot_id, TAXABLE, "SEC-1", date(2024, 1, 2), date(2025, 6, day), D(units), D(cost), D(proceeds)
    )


def bought(event_id: str, units: str, day: int, account: str = IRA) -> Buy:
    return Buy(event_id, date(2025, 6, day), date(2025, 6, day + 1), account, "SEC-1", D(units), D(10), -D(units) * 10)


def test_replacement_shares_are_matched_to_the_lots_in_the_order_sold() -> None:
    # One sale closes 300 then 400 shares, each at a loss of 3 a share (900 and 1,200); 500 replacement
    # shares replace the first lot wholly (900), then 200 of the second (1,200 x 200 / 400 = 600).
    lots = [sold("L-A", "300", "3900", "3000"), sold("L-B", "400", "5200", "4000")]
    assert disallowed_losses(lots, [bought("E-B1", "500", 20)], {TAXABLE}) == {
        "E-S1:L-A": D("900.00"),
        "E-S1:L-B": D("600.00"),
    }


def test_one_purchase_replaces_shares_once_across_two_loss_sales() -> None:
    # 100 replacement shares on 6/15, inside the window of both sales; the earlier sale takes them all.
    first = sold("L-A", "100", "1500", "1000", "E-S1", day=10)
    second = sold("L-B", "100", "1500", "1000", "E-S2", day=12)
    assert disallowed_losses([first, second], [bought("E-B1", "100", 15)], {TAXABLE}) == {"E-S1:L-A": D("500.00")}


def test_a_purchase_partly_sold_in_the_same_sale_still_replaces_with_the_shares_kept() -> None:
    # Reviewer B, slice 7 round 1: 100 shares bought on 6/1, 50 of them sold on 6/10 with 100 older shares at
    # a 500 loss. The 50 kept replace half the loss shares: 250 disallowed, in an IRA; refused in a taxable
    # account, whose replacement lot would need the disallowed loss in its basis.
    lots = [sold("L-A", "100", "1500", "1000"), sold("L-E-B1", "50", "500", "500")]
    assert disallowed_losses(lots, [bought("E-B1", "100", 1)], {TAXABLE}) == {"E-S1:L-A": D("250.00")}
    with pytest.raises(TaxFactsError, match=r"E-B1 replaces"):
        disallowed_losses(lots, [bought("E-B1", "100", 1, TAXABLE)], {TAXABLE})


def test_shares_bought_and_sold_in_the_same_sale_replace_nothing() -> None:
    # The 6/1 purchase made lot L-E-B1, sold in the same sale as L-A: it is not a replacement.
    lots = [sold("L-A", "100", "1500", "1000"), sold("L-E-B1", "50", "500", "500")]
    assert disallowed_losses(lots, [bought("E-B1", "50", 1)], {TAXABLE}) == {}


def test_purchases_outside_thirty_days_and_gains_are_left_alone() -> None:
    loss = sold("L-A", "100", "1500", "1000", day=10)
    gain = sold("L-B", "100", "500", "1000", "E-S2", day=10)
    outside = Buy("E-B1", date(2025, 7, 11), date(2025, 7, 12), IRA, "SEC-1", D(100), D(10), D(-1000))
    assert disallowed_losses([loss, gain], [outside], {TAXABLE}) == {}


def test_a_replacement_in_a_taxable_account_is_refused() -> None:
    with pytest.raises(TaxFactsError, match=r"E-B1 replaces shares sold at a loss in E-S1"):
        disallowed_losses([sold("L-A", "100", "1500", "1000")], [bought("E-B1", "100", 20, TAXABLE)], {TAXABLE})


def test_released_rsu_shares_count_as_a_replacement() -> None:
    # An RSU release of the same stock within thirty days acquires shares (§ 1091(a)): here into the taxable
    # account, so the facts refuse it rather than leave the released lot's basis unadjusted.
    release = Vest("E-V1", date(2025, 6, 20), TAXABLE, "SEC-1", D(40), D(10))
    with pytest.raises(TaxFactsError, match=r"E-V1 replaces"):
        disallowed_losses([sold("L-A", "100", "1500", "1000")], [release], {TAXABLE})


@pytest.mark.parametrize(
    ("born", "died", "age"),
    [
        (date(1960, 6, 30), None, 65),  # 65th birthday in the year
        (date(1961, 1, 1), None, 65),  # Pub. 501: 65 on 31 December 2025, the day before the birthday
        (date(1961, 1, 2), None, 64),
        # Reviewer A, slice 7 round 1: died 16 May 2025, before the 65th birthday on 7 September: 64.
        (date(1960, 9, 7), date(2025, 5, 16), 64),
        (date(1960, 5, 17), date(2025, 5, 16), 65),  # died the day before the birthday: 65
    ],
)
def test_the_age_for_the_year_is_at_year_end_or_at_death(born: date, died: date | None, age: int) -> None:
    assert age_for_the_year(born, died) == age
