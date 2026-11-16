"""The keys' Form 8606 and capital loss carryover against IRS worked examples and hand-worked cases.

IRS examples:
- Publication 590-B (2025), chapter 1, "Rose Green" and Worksheet 1-1 (Illustrated), with her
  illustrated Form 8606 (2025): basis 300, 2025 contributions 2,000, a 5,000 conversion, a year-end
  value of 20,000; line 7 of the worksheet 0.092, nontaxable 460, Form 8606 lines 16, 17 and 18
  5,000, 460 and 4,540.
- Publication 590-B (2025), chapter 2, "Amelia": she "converted all $80,000 in her traditional IRA",
  "$20,000 of the amount converted is her basis", and she "included $60,000 ($80,000 - $20,000)".
- Publication 550 (2021), chapter 4, Capital Losses, "Bob and Gloria": a $7,000 capital loss, joint
  taxable income of $26,000, a $3,000 deduction, and $4,000 carried over; had the loss been $2,000,
  "They would have no carryover." The 2025 worksheet in the Schedule D instructions is the same.

Every other expected value is worked by hand in the comment beside it.
"""

from decimal import Decimal

from casebook.keys.tax_lines import capital_loss_carryover, form_8606, taxable_retirement
from casebook.model.tax import Filer, IraFlows, TaxUnitFacts

D = Decimal


def _flows(
    *,
    basis_prior: str = "0",
    nondeductible: str = "0",
    distributions: str = "0",
    conversions: str = "0",
    qcd: str = "0",
    year_end: str = "0",
    person_id: str = "P1",
) -> IraFlows:
    return IraFlows(
        person_id=person_id,
        basis_prior=D(basis_prior),
        nondeductible_contributions=D(nondeductible),
        distributions=D(distributions),
        conversions=D(conversions),
        qcd=D(qcd),
        year_end_value=D(year_end),
    )


def _facts(
    *,
    filing_status: str = "married_filing_jointly",
    short: str = "0",
    long: str = "0",
    carry_short: str = "0",
    carry_long: str = "0",
    iras: tuple[IraFlows, ...] = (),
    plan: str = "0",
    inherited: str = "0",
) -> TaxUnitFacts:
    zero = D(0)
    return TaxUnitFacts(
        household_id="HH-0001",
        tax_unit_id="HH-0001-T1",
        filing_status=filing_status,
        filers=(Filer("P1", 60, zero, zero),),
        taxable_interest=zero,
        tax_exempt_interest=zero,
        ordinary_dividends=zero,
        qualified_dividends=zero,
        short_term_gain=D(short),
        long_term_gain=D(long),
        carryforward_short=D(carry_short),
        carryforward_long=D(carry_long),
        iras=iras,
        plan_distributions=D(plan),
        inherited_ira_distributions=D(inherited),
        federal_withholding=zero,
    )


# Form 8606: IRS worked examples


def test_rose_green_pub_590b_worksheet_1_1() -> None:
    # Worksheet 1-1 line 2 counts every 2025 contribution, deductible or not, so the key gets all
    # 2,000 on line 1. Her Form 8606 line 14 (340) uses only the 500 found nondeductible after the
    # deduction worksheet, a step the book has no use for, so line 14 is not compared here.
    lines = form_8606(_flows(basis_prior="300", nondeductible="2000", conversions="5000", year_end="20000"))
    assert lines.line_3 == D("2300")
    assert lines.line_9 == D("25000")
    assert lines.line_10 == D("0.092")
    assert lines.line_11 == D("460")
    assert lines.line_16 == D("5000")
    assert lines.line_17 == D("460")
    assert lines.line_18 == D("4540")
    assert lines.line_15c == D("0")


def test_amelia_pub_590b_conversion_of_whole_ira_with_basis() -> None:
    lines = form_8606(_flows(basis_prior="20000", conversions="80000", year_end="0"))
    assert lines.line_10 == D("0.250")
    assert lines.line_11 == D("20000")
    assert lines.line_18 == D("60000")
    assert lines.line_14 == D("0")
    assert lines.taxable == D("60000")


# Form 8606: hand-worked cases for the book's shapes


def test_backdoor_roth_with_a_rollover_ira_is_pro_rata() -> None:
    # Line 3 7,000; line 9 93,000 + 0 + 7,000 = 100,000; line 10 0.070; line 11 490;
    # line 14 7,000 - 490 = 6,510; line 18 7,000 - 490 = 6,510.
    lines = form_8606(_flows(nondeductible="7000", conversions="7000", year_end="93000"))
    assert lines.line_10 == D("0.070")
    assert lines.line_11 == D("490")
    assert lines.line_13 == D("490")
    assert lines.line_14 == D("6510")
    assert lines.line_18 == D("6510")
    assert lines.taxable == D("6510")


def test_line_10_rounds_to_three_places() -> None:
    # 7,000 / 307,000 = 0.02280... -> 0.023; line 11 7,000 x 0.023 = 161; line 14 6,839.
    lines = form_8606(_flows(nondeductible="7000", conversions="7000", year_end="300000"))
    assert lines.line_10 == D("0.023")
    assert lines.line_11 == D("161.00")
    assert lines.line_14 == D("6839.00")
    assert lines.line_18 == D("6839.00")


def test_conversion_and_distribution_with_basis() -> None:
    # Line 3 12,000; line 9 160,000 + 10,000 + 30,000 = 200,000; line 10 0.060;
    # line 11 1,800; line 12 600; line 13 2,400; line 14 9,600; line 15c 9,400; line 18 28,200.
    lines = form_8606(_flows(basis_prior="12000", distributions="10000", conversions="30000", year_end="160000"))
    assert lines.line_10 == D("0.060")
    assert lines.line_11 == D("1800")
    assert lines.line_12 == D("600")
    assert lines.line_14 == D("9600")
    assert lines.line_15c == D("9400")
    assert lines.line_18 == D("28200")
    assert lines.taxable == D("37600")


def test_qcd_stays_off_line_7_and_leaves_the_ratio_alone() -> None:
    # Line 9 380,000 + 20,000 + 0 = 400,000 (the 10,000 QCD is not on line 7); line 10 0.020;
    # line 12 400; line 14 7,600; line 15c 19,600. No conversion, so Part II is blank.
    lines = form_8606(_flows(basis_prior="8000", distributions="20000", qcd="10000", year_end="380000"))
    assert lines.line_7 == D("20000")
    assert lines.line_9 == D("400000")
    assert lines.line_12 == D("400")
    assert lines.line_14 == D("7600")
    assert lines.line_15c == D("19600")
    assert lines.line_16 is None
    assert lines.line_18 is None


def test_line_10_is_capped_at_one() -> None:
    # Basis 10,000 against an emptied IRA: 10,000 / 6,000 is over 1, so 1.000; all 6,000 is
    # nontaxable and 4,000 of basis carries on.
    lines = form_8606(_flows(basis_prior="10000", distributions="6000", year_end="0"))
    assert lines.line_10 == D("1.000")
    assert lines.line_12 == D("6000")
    assert lines.line_14 == D("4000")
    assert lines.taxable == D("0")


def test_no_distribution_carries_line_3_to_line_14() -> None:
    lines = form_8606(_flows(basis_prior="3000", nondeductible="7000", year_end="50000"))
    assert lines.line_14 == D("10000")
    assert lines.line_6 is None
    assert lines.line_10 is None
    assert lines.taxable == D("0")


def test_taxable_retirement_adds_both_people_and_the_plans() -> None:
    # P1's backdoor conversion 6,510 + P2's distribution 19,600 (QCD excluded) + 401(k) 15,000
    # + inherited IRA 12,000 = 53,110.
    facts = _facts(
        iras=(
            _flows(nondeductible="7000", conversions="7000", year_end="93000", person_id="P1"),
            _flows(basis_prior="8000", distributions="20000", qcd="10000", year_end="380000", person_id="P2"),
        ),
        plan="15000",
        inherited="12000",
    )
    assert taxable_retirement(facts) == D("53110")


# Capital loss carryover: IRS worked example


def test_bob_and_gloria_pub_550_short_term() -> None:
    facts = _facts(short="-7000")
    assert capital_loss_carryover(facts, D("26000"), D(0)) == (D("4000"), D("0"))


def test_bob_and_gloria_pub_550_long_term() -> None:
    facts = _facts(long="-7000")
    assert capital_loss_carryover(facts, D("26000"), D(0)) == (D("0"), D("4000"))


def test_bob_and_gloria_pub_550_smaller_loss_has_no_carryover() -> None:
    facts = _facts(short="-2000")
    assert capital_loss_carryover(facts, D("26000"), D(0)) == (D("0"), D("0"))


# Capital loss carryover: hand-worked cases


def test_loss_above_the_limit_split_short_and_long() -> None:
    # Sch. D 7 -8,000, 15 -2,000, 16 -10,000, 21 -3,000. Worksheet: 4 = 3,000; 5 8,000; 6 0;
    # 7 3,000; 8 5,000. 9 2,000; 10 0; 11 max(3,000 - 8,000, 0) = 0; 12 0; 13 2,000.
    facts = _facts(filing_status="single", short="-8000", long="-2000")
    assert capital_loss_carryover(facts, D("40000"), D(0)) == (D("5000"), D("2000"))


def test_carryforward_in_joins_the_year_s_loss() -> None:
    # Sch. D 7 = -2,000 - 1,000 = -3,000; 15 -9,000; 21 -3,000. Worksheet: 4 3,000; 5 3,000;
    # 7 3,000; 8 0. 9 9,000; 10 0; 11 0; 13 9,000.
    facts = _facts(filing_status="single", short="-2000", long="-9000", carry_short="1000")
    assert capital_loss_carryover(facts, D("50000"), D(0)) == (D("0"), D("9000"))


def test_short_loss_against_a_long_gain() -> None:
    # Sch. D 7 -10,000, 15 4,000, 16 -6,000. Worksheet: 4 3,000; 5 10,000; 6 4,000; 7 7,000;
    # 8 3,000. Line 15 is a gain, so no long-term carryover.
    facts = _facts(short="-10000", long="4000")
    assert capital_loss_carryover(facts, D("60000"), D(0)) == (D("3000"), D("0"))


def test_long_loss_against_a_short_gain() -> None:
    # Sch. D 7 2,000, 15 -9,000, 16 -7,000. Worksheet: 4 3,000; 5 0; 9 9,000; 10 2,000;
    # 11 3,000; 12 5,000; 13 4,000.
    facts = _facts(short="2000", long="-9000")
    assert capital_loss_carryover(facts, D("60000"), D(0)) == (D("0"), D("4000"))


def test_negative_taxable_income_carries_the_unused_deduction() -> None:
    # Line 1 (1,000); 2 3,000; 3 2,000; 4 2,000; 5 5,000; 7 2,000; 8 3,000.
    facts = _facts(filing_status="single", short="-5000")
    assert capital_loss_carryover(facts, D("-1000"), D(0)) == (D("3000"), D("0"))


def test_married_filing_separately_limit_is_1500() -> None:
    # Sch. D 15 -4,000, 21 -1,500. Worksheet: 4 1,500; 5 0; 9 4,000; 11 1,500; 12 1,500; 13 2,500.
    facts = _facts(filing_status="married_filing_separately", long="-4000")
    assert capital_loss_carryover(facts, D("30000"), D(0)) == (D("0"), D("2500"))


def test_net_gain_carries_nothing() -> None:
    facts = _facts(short="-2000", long="5000", carry_long="1000")
    assert capital_loss_carryover(facts, D("90000"), D(0)) == (D("0"), D("0"))


def test_the_senior_deduction_is_added_back_as_a_section_151_deduction() -> None:
    # Reviewer A, slice 7 round 1. 26 U.S.C. § 1212(b)(2)(B)(ii) adds back the deduction allowed under § 151,
    # and the 2025 senior deduction is § 151(d)(5)(C). Single, 70: taxable income (2,750) with the 6,000 senior
    # deduction in it. Line 1 3,250; 2 3,000; 3 6,250; 4 3,000; 5 7,000; 6 0; 7 3,000; 8 4,000.
    facts = _facts(filing_status="single", short="-7000")
    assert capital_loss_carryover(facts, D("-2750"), D("6000")) == (D("4000"), D("0"))
    # Without the add-back the worksheet would carry 6,750: line 3 250, line 4 250.
    assert capital_loss_carryover(facts, D("-2750"), D(0)) == (D("6750"), D("0"))
