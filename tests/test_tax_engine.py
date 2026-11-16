"""The in-house engine against hand-worked figures and the IRS's own examples.

Every expected value is a literal: from the planning probe's three hand-worked cases (A, B and C, which
Tax-Calculator 6.9.1 and PolicyEngine-US matched to the dollar), from an IRS publication's worked example, or
worked by hand in the comment beside it from the 2025 figures (Rev. Proc. 2024-40; Pub. L. 119-21).
"""

from dataclasses import replace
from decimal import Decimal

import pytest

from casebook.model.tax import ZERO, Filer, IraFlows, TaxUnitFacts
from casebook.rules import load_rules
from casebook.tax.engine import EngineError, compute
from casebook.tax.engine.form_8606 import form_8606
from casebook.tax.engine.tax_computation import regular_tax

D = Decimal
MFJ = "married_filing_jointly"


def facts(status: str, filers: tuple[Filer, ...], **fields: object) -> TaxUnitFacts:
    values: dict[str, object] = {
        "household_id": "HH-0001",
        "tax_unit_id": "TU-1",
        "filing_status": status,
        "filers": filers,
        "taxable_interest": ZERO,
        "tax_exempt_interest": ZERO,
        "ordinary_dividends": ZERO,
        "qualified_dividends": ZERO,
        "short_term_gain": ZERO,
        "long_term_gain": ZERO,
        "carryforward_short": ZERO,
        "carryforward_long": ZERO,
        "iras": (),
        "plan_distributions": ZERO,
        "inherited_ira_distributions": ZERO,
        "federal_withholding": ZERO,
    }
    values.update(fields)
    return TaxUnitFacts(**values)  # type: ignore[arg-type]


def person(age: int, wages: str = "0", social_security: str = "0", person_id: str = "P1") -> Filer:
    return Filer(person_id, age, D(wages), D(social_security))


def ira(
    distributions: str = "0",
    conversions: str = "0",
    basis_prior: str = "0",
    nondeductible: str = "0",
    year_end_value: str = "0",
    qcd: str = "0",
    person_id: str = "P1",
) -> IraFlows:
    return IraFlows(
        person_id, D(basis_prior), D(nondeductible), D(distributions), D(conversions), D(qcd), D(year_end_value)
    )


# The planning probe (review/probes/tax/cases.json): hand figures that Tax-Calculator 6.9.1 matched.

CASE_A = facts(
    MFJ,
    (person(45, "420000"), person(45, person_id="P2")),
    taxable_interest=D(12000),
    ordinary_dividends=D(30000),
    qualified_dividends=D(30000),
    long_term_gain=D(80000),
    state_local_taxes=D(38000),
    mortgage_interest=D(18000),
)
# Case A as the book would hold it: no state and local taxes or mortgage interest, so the standard deduction.
STANDARD_A = replace(CASE_A, state_local_taxes=ZERO, mortgage_interest=ZERO)


def test_case_a_high_income_couple_with_the_salt_phase_down() -> None:
    result = compute(CASE_A)
    summary = result.summary
    assert summary.agi == D("542000.00")
    # SALT: 40,000 less 30% of (542,000 - 500,000) = 27,400; with 18,000 of mortgage interest, 45,400 itemized.
    assert result.deductions.schedule_a.salt_deduction == D("27400.00")
    assert result.deductions.itemized
    assert summary.taxable_income == D("496600.00")
    assert summary.niit == D("4636.00")
    assert summary.additional_medicare == D("1530.00")
    assert summary.income_tax == D("99614.00")
    # Ordinary 386,600 - 110,000 of gains and dividends: in the 24% bracket (206,700 to 394,600).
    assert summary.bracket == D("0.24")


def test_case_b_single_retiree_with_social_security_and_the_senior_deduction() -> None:
    retiree = facts(
        "single",
        (person(74, social_security="38000"),),
        ordinary_dividends=D(9000),
        qualified_dividends=D(9000),
        long_term_gain=D(15000),
        iras=(ira(distributions="62000", year_end_value="400000"),),
    )
    result = compute(retiree)
    summary = result.summary
    assert summary.taxable_social_security == D("32300.00")
    assert summary.agi == D("118300.00")
    # 6,000 less 6% of (118,300 - 75,000) = 3,402.
    assert result.deductions.senior == D("3402.00")
    assert summary.taxable_income == D("97148.00")
    assert summary.income_tax == D("14606.56")
    assert summary.niit == ZERO
    assert summary.additional_medicare == ZERO
    assert summary.taxable_ira == D("62000.00")
    assert summary.bracket == D("0.22")


def test_case_c_couple_with_a_capped_capital_loss() -> None:
    couple = facts(
        MFJ,
        (person(38, "130000"), person(36, "80000", person_id="P2")),
        taxable_interest=D(2000),
        long_term_gain=D(-9000),
    )
    summary = compute(couple).summary
    assert summary.agi == D("209000.00")
    assert summary.taxable_income == D("177500.00")
    assert summary.income_tax == D("28878.00")
    assert summary.niit == ZERO
    assert summary.additional_medicare == ZERO
    # 9,000 loss less the 3,000 allowed; taxable income is positive, so all 6,000 carries, long-term.
    assert summary.carryforward_short == ZERO
    assert summary.carryforward_long == D("6000")
    assert summary.bracket == D("0.22")


def test_case_a_on_the_standard_deduction_as_the_book_would_hold_it() -> None:
    # Hand-worked: 542,000 - 31,500 = 510,500; ordinary 400,500 taxes at 82,286 (2,385 + 8,772 + 24,145 +
    # 45,096 + 1,888); 110,000 at 15% = 16,500; regular tax 98,786 plus NIIT 4,636 = 103,422.
    summary = compute(STANDARD_A).summary
    assert summary.taxable_income == D("510500.00")
    assert summary.income_tax == D("103422.00")
    assert summary.bracket == D("0.32")


def test_the_qualified_dividends_worksheet_on_case_a_figures() -> None:
    # 386,600 ordinary on the joint schedule is 78,478; 110,000 at 15% is 16,500.
    worksheet = regular_tax(D(496600), D(30000), D(80000), MFJ, load_rules())
    assert worksheet.line_22 == D("78478.00")
    assert worksheet.line_18 == D("16500.00")
    assert worksheet.line_25 == D("94978.00")


# Form 8606


def test_form_8606_on_the_pub_590_b_worksheet_1_1_example() -> None:
    """Pub. 590-B (2025), Worksheet 1-1, illustrated: Rose Green, basis 300 at 31 December 2024, 2,000
    contributed for 2025, a 5,000 distribution converted to a Roth IRA, 20,000 in her IRAs at year end. The IRS
    figures: 2,300; 25,000; 0.092; 460 nontaxable; 4,540 taxable and allocable to the conversion; 0 taxable
    otherwise. The worksheet's lines are Form 8606's lines 3 to 18 when the whole contribution is
    nondeductible, as here. (The IRS's illustrated Form 8606 itself takes only 500 as nondeductible, from the
    deduction-limit computation that the book never needs.) Line 14 is line 3 less line 13: 2,300 - 460."""
    form = form_8606(ira(conversions="5000", basis_prior="300", nondeductible="2000", year_end_value="20000"))
    assert form.line_3 == D("2300")
    assert form.line_9 == D("25000")
    assert form.line_10 == D("0.092")
    assert form.line_11 == D("460.00")
    assert form.line_13 == D("460.00")
    assert form.line_15c == ZERO
    assert form.line_16 == D("5000")
    assert form.line_17 == D("460.00")
    assert form.line_18 == D("4540.00")
    assert form.line_14 == D("1840.00")


def test_form_8606_rounds_line_10_to_three_places_and_splits_distributions_and_conversions() -> None:
    # 14,000 / (180,000 + 10,000 + 7,000) = 0.07107 -> 0.071. Conversion 7,000 x 0.071 = 497; distribution
    # 10,000 x 0.071 = 710; nontaxable 1,207; basis left 12,793; taxable 9,290 + 6,503 = 15,793. The QCD stays
    # off line 7 and out of income.
    flows = ira("10000", "7000", basis_prior="7000", nondeductible="7000", year_end_value="180000", qcd="5000")
    form = form_8606(flows)
    assert form.line_10 == D("0.071")
    assert (form.line_11, form.line_12, form.line_13) == (D("497.00"), D("710.00"), D("1207.00"))
    assert form.line_14 == D("12793.00")
    assert (form.line_15c, form.line_18) == (D("9290.00"), D("6503.00"))
    summary = compute(facts("single", (person(72),), iras=(flows,))).summary
    assert summary.taxable_ira == D("15793.00")
    assert summary.ira_basis == (("P1", D("12793.00")),)


def test_form_8606_caps_line_10_at_one() -> None:
    # A backdoor conversion that lost value: 7,000 basis, 6,900 converted, nothing left. 7,000 / 6,900 > 1.
    form = form_8606(ira(conversions="6900", nondeductible="7000"))
    assert form.line_10 == D("1")
    assert form.line_18 == ZERO
    assert form.line_14 == D("100.00")


def test_form_8606_with_no_distribution_carries_line_3_to_line_14() -> None:
    form = form_8606(ira(basis_prior="3000", nondeductible="7000", year_end_value="50000"))
    assert form.line_14 == D("10000")
    assert form.line_10 == ZERO
    assert form.taxable == ZERO


def test_inherited_ira_and_plan_distributions_are_fully_taxable_and_not_investment_income() -> None:
    # AGI 250,000 + 5,000 + 40,000 + 10,000 = 305,000. NII is the 5,000 of interest alone, under the 105,000
    # over the threshold: 190. Additional Medicare 0.9% of 50,000 = 450. Taxable 289,250 on the single
    # schedule: 1,192.50 + 4,386 + 12,072.50 + 22,548 + 17,032 + 13,553.75 = 70,784.75; plus 190.
    result = compute(
        facts(
            "single",
            (person(50, "250000"),),
            taxable_interest=D(5000),
            inherited_ira_distributions=D(40000),
            plan_distributions=D(10000),
        )
    )
    summary = result.summary
    assert summary.agi == D("305000")
    # The summary's retirement income is Form 1040 lines 4b and 5b together; line 4b alone is the inherited IRA.
    assert summary.taxable_ira == D("50000")
    assert result.form_1040.taxable_ira == D("40000")
    assert result.form_1040.taxable_pensions == D("10000")
    assert summary.niit == D("190.00")
    assert summary.additional_medicare == D("450.00")
    assert summary.income_tax == D("70974.75")
    assert summary.bracket == D("0.35")


# The capital loss carryover


def test_capital_loss_carryover_on_the_pub_550_example() -> None:
    """Pub. 550 (2025), Capital Losses, Example: Bob and Shelly have a 7,000 capital loss and taxable income of
    26,000 on a joint return; they deduct 3,000 and carry 4,000 to 2026. Wages of 60,500 less the 3,000 and the
    31,500 standard deduction give their 26,000."""
    result = compute(facts(MFJ, (person(40, "60500"), person(40, person_id="P2")), long_term_gain=D(-7000)))
    assert result.summary.taxable_income == D("26000")
    assert result.schedule_d.loss_allowed == D("3000")
    assert result.summary.carryforward_short + result.summary.carryforward_long == D("4000")
    assert result.summary.carryforward_long == D("4000")


def test_capital_loss_within_the_limit_carries_nothing_on_the_pub_550_example() -> None:
    """The same example: "If their capital loss had been $2,000, their capital loss deduction would have been
    $2,000. They would have no carryover." """
    result = compute(facts(MFJ, (person(40, "59500"), person(40, person_id="P2")), long_term_gain=D(-2000)))
    assert result.schedule_d.loss_allowed == D("2000")
    assert (result.summary.carryforward_short, result.summary.carryforward_long) == (ZERO, ZERO)


def test_capital_loss_carryover_worksheet_splits_short_and_long() -> None:
    # Net short -5,000; long 1,000 less 2,000 carried in = -1,000; line 16 -6,000, 3,000 allowed. Worksheet:
    # line 4 = 3,000; line 5 = 5,000; line 6 = 0; line 8 = 5,000 - 3,000 = 2,000 short. Line 9 = 1,000;
    # line 10 = 0; line 11 = max(0, 3,000 - 5,000) = 0; line 13 = 1,000 long.
    summary = compute(
        facts(
            "single",
            (person(50, "100000"),),
            short_term_gain=D(-5000),
            long_term_gain=D(1000),
            carryforward_long=D(2000),
        )
    ).summary
    assert (summary.carryforward_short, summary.carryforward_long) == (D("2000"), D("1000"))


def test_capital_loss_carryover_with_negative_taxable_income_carries_the_whole_loss() -> None:
    # Wages 10,000 less the 3,000 allowed: AGI 7,000; less 15,750: -8,750 on worksheet line 1. Line 3 is
    # max(0, -8,750 + 3,000) = 0, so line 4 is 0 and the whole 8,000 short-term loss carries (§ 1212(b)(2)).
    summary = compute(facts("single", (person(40, "10000"),), short_term_gain=D(-8000))).summary
    assert summary.taxable_income == ZERO
    assert (summary.carryforward_short, summary.carryforward_long) == (D("8000"), ZERO)


# Social Security, the senior deduction, the bracket and the AMT


def test_tax_exempt_interest_counts_toward_taxable_social_security() -> None:
    # Line 5: 15,000 + 10,000 + 20,000 = 45,000; over 25,000 by 20,000; 4,500 + 85% of 11,000 = 13,850,
    # under 85% of 30,000. AGI 23,850 less 17,750 and the full 6,000 senior deduction: 100, taxed 10.00.
    summary = compute(
        facts(
            "single",
            (person(70, social_security="30000"),),
            tax_exempt_interest=D(20000),
            iras=(ira(distributions="10000", year_end_value="90000"),),
        )
    ).summary
    assert summary.taxable_social_security == D("13850.00")
    assert summary.agi == D("23850.00")
    assert summary.taxable_income == D("100.00")
    assert summary.income_tax == D("10.00")


def test_senior_deduction_phases_out_for_each_spouse() -> None:
    # 170,000 is 20,000 over 150,000: each spouse's 6,000 less 1,200, 9,600 in all. Standard 31,500 + 2 x
    # 1,600 = 34,700. Taxable 125,700: 2,385 + 8,772 + 6,325 = 17,482.
    result = compute(
        facts(MFJ, (person(70), person(68, person_id="P2")), iras=(ira("170000", year_end_value="1000000"),))
    )
    assert result.deductions.senior == D("9600.00")
    assert result.deductions.standard == D("34700")
    assert result.summary.taxable_income == D("125700.00")
    assert result.summary.income_tax == D("17482.00")


def test_senior_deduction_is_gone_at_175_000_single() -> None:
    # 6% of (180,000 - 75,000) = 6,300, more than 6,000. Taxable 180,000 - 17,750 = 162,250.
    result = compute(facts("single", (person(66),), iras=(ira("180000", year_end_value="500000"),)))
    assert result.deductions.senior == ZERO
    assert result.summary.taxable_income == D("162250.00")


@pytest.mark.parametrize(
    ("wages", "bracket", "income_tax"),
    [
        # 64,225 - 15,750 = 48,475, the top of the 12% bracket: 1,192.50 + 4,386 = 5,578.50.
        ("64225", "0.12", "5578.50"),
        # One cent more: the last cent is taxed at 22%.
        ("64225.01", "0.22", "5578.50"),
    ],
)
def test_bracket_is_the_rate_on_the_last_dollar(wages: str, bracket: str, income_tax: str) -> None:
    summary = compute(facts("single", (person(40, wages),))).summary
    assert summary.bracket == D(bracket)
    assert summary.income_tax == D(income_tax)


def test_bracket_with_no_ordinary_income_is_ten_percent() -> None:
    # 20,000 of qualified dividends less 15,750: 4,250 taxable, none of it ordinary, all at 0%.
    summary = compute(facts("single", (person(40),), ordinary_dividends=D(20000), qualified_dividends=D(20000))).summary
    assert summary.bracket == D("0.10")
    assert summary.income_tax == ZERO


def test_amt_does_not_apply_at_the_books_incomes() -> None:
    # Case A on the standard deduction: AMTI = AGI 542,000; less 137,000 = 405,000. Part III: 295,000 ordinary
    # at 26% to 239,100 and 28% over (62,166 + 15,652) plus 110,000 at 15% (16,500) = 94,318, under the
    # regular tax of 98,786.
    result = compute(STANDARD_A)
    amt = result.form_6251
    assert amt.line_4 == D("542000.00")
    assert amt.line_6 == D("405000.00")
    assert amt.line_7 == D("94318.00")
    assert amt.line_10 == D("98786.00")
    assert amt.line_11 == ZERO


def test_amt_adds_back_an_itemizers_state_and_local_taxes() -> None:
    # Case A itemized: 542,000 - 45,400 + 27,400 = 524,000; less 137,000 = 387,000; 277,000 ordinary taxes at
    # 72,778, 110,000 at 15% is 16,500: 89,278, under 94,978.
    amt = compute(CASE_A).form_6251
    assert amt.line_4 == D("524000.00")
    assert amt.line_7 == D("89278.00")
    assert amt.line_11 == ZERO


def test_a_separate_filer_with_social_security_is_refused() -> None:
    with pytest.raises(EngineError, match="lived apart"):
        compute(facts("married_filing_separately", (person(70, social_security="20000"),)))


def test_an_unknown_filing_status_is_refused() -> None:
    with pytest.raises(EngineError, match="unknown filing status"):
        compute(facts("qualifying_surviving_spouse", (person(40, "50000"),)))


def test_a_separate_filer_gets_the_married_additional_amount_and_no_senior_deduction() -> None:
    # Standard 15,750 + 1,600 for one spouse 65 or over; no senior deduction on a separate return. Taxable
    # 100,000 - 17,350 = 82,650: 1,192.50 + 4,386 + 22% of 34,175 (7,518.50) = 13,097. AMTI 100,000 less the
    # 68,500 exemption, 31,500 at 26% = 8,190, under the regular tax.
    result = compute(facts("married_filing_separately", (person(66, "100000"),)))
    assert result.deductions.senior == ZERO
    assert result.summary.taxable_income == D("82650")
    assert result.summary.income_tax == D("13097.00")
    assert result.form_6251.line_7 == D("8190.00")
    assert result.form_6251.line_11 == ZERO


def test_the_loss_carryover_adds_back_the_senior_deduction() -> None:
    # Reviewer A, slice 7 round 1. Single, 70, a 24,000 pension and a 7,000 short-term loss. AGI 24,000 - 3,000 =
    # 21,000; standard deduction 15,750 + 2,000 = 17,750; senior deduction 6,000 (MAGI under 75,000); taxable
    # income before the floor (2,750). Adjusted taxable income adds back the § 151 deduction: 3,250, so the
    # 3,000 allowed is used in full and 4,000 carries to 2026 (§ 1212(b)(2)(B)(ii)).
    result = compute(facts("single", (person(70),), plan_distributions=D(24000), short_term_gain=D(-7000)))
    assert result.deductions.senior == D("6000")
    assert result.summary.senior_deduction == D("6000")
    assert result.summary.taxable_income == ZERO
    assert (result.summary.carryforward_short, result.summary.carryforward_long) == (D("4000"), ZERO)


def test_a_separate_filer_s_salt_limit_is_halved_after_the_phase_down() -> None:
    # Reviewer B, slice 7 round 1, worked in tests/test_tax_crosscheck.py: line 9 25,000, halved to 12,500.
    separate = facts(
        "married_filing_separately",
        (person(45, "300000"),),
        state_local_taxes=D(40000),
        mortgage_interest=D(20000),
    )
    result = compute(separate)
    assert result.deductions.schedule_a.salt_deduction == D("12500.00")
    assert result.summary.taxable_income == D("267500.00")
    assert result.summary.income_tax == D("63172.25")
    # Under the threshold, the separate filer takes half of the 40,000 cap: 20,000 of 25,000 paid.
    low = compute(replace(separate, filers=(person(45, "200000"),), state_local_taxes=D(25000)))
    assert low.deductions.schedule_a.salt_deduction == D("20000.00")
    # Far over it, half the 10,000 floor: 5,000.
    high = compute(replace(separate, filers=(person(45, "900000"),)))
    assert high.deductions.schedule_a.salt_deduction == D("5000.00")
