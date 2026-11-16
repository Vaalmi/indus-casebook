"""Tax-Calculator through `tax/crosscheck.py`, on hand-worked 2025 cases.

Every expected figure below is worked by hand from the 2025 law, not read back from Tax-Calculator.
The 2025 figures used (Rev. Proc. 2024-40 as amended by Pub. L. 119-21, sec. 70102 and 70103):
- Standard deduction: single 15,750; joint 31,500; head of household 23,625. Additional for 65 or older,
  single: 2,000. Senior deduction (Pub. L. 119-21, sec. 70103): 6,000, less 6% of MAGI over 75,000 (single).
- Ordinary brackets, joint: 10% to 23,850; 12% to 96,950; 22% to 206,700; 24% to 394,600; 32% to 501,050.
  Single: 10% to 11,925; 12% to 48,475; 22% to 103,350. Head of household: 10% to 17,000; 12% to 64,850;
  22% to 103,350.
- Qualified dividends and long-term gain: 0% to taxable income of 48,350 (single), 96,700 (joint); 15% to
  533,400 (single), 600,050 (joint).
- NIIT (IRC 1411): 3.8% of the lesser of net investment income and MAGI over 250,000 (joint).
- Additional Medicare Tax (IRC 3101(b)(2)): 0.9% of wages over 250,000 (joint).
- Capital loss limit (IRC 1211(b)): 3,000. Taxable Social Security (IRC 86): single base 25,000 and 34,000.
"""

import dataclasses
from decimal import Decimal

from casebook.model.tax import ZERO, Filer, IraFlows, TaxSummary, TaxUnitFacts
from casebook.tax.crosscheck import crosscheck

D = Decimal


def unit(
    tax_unit_id: str,
    filing_status: str,
    filers: tuple[Filer, ...],
    *,
    interest: str = "0",
    dividends: str = "0",
    qualified: str = "0",
    short: str = "0",
    long: str = "0",
    carry_short: str = "0",
    carry_long: str = "0",
    iras: tuple[IraFlows, ...] = (),
) -> TaxUnitFacts:
    return TaxUnitFacts(
        household_id=f"H-{tax_unit_id}",
        tax_unit_id=tax_unit_id,
        filing_status=filing_status,
        filers=filers,
        taxable_interest=D(interest),
        tax_exempt_interest=ZERO,
        ordinary_dividends=D(dividends),
        qualified_dividends=D(qualified),
        short_term_gain=D(short),
        long_term_gain=D(long),
        carryforward_short=D(carry_short),
        carryforward_long=D(carry_long),
        iras=iras,
        plan_distributions=ZERO,
        inherited_ira_distributions=ZERO,
        federal_withholding=ZERO,
    )


def filer(person_id: str, age: int, wages: str = "0", social_security: str = "0") -> Filer:
    return Filer(person_id=person_id, age=age, wages=D(wages), social_security=D(social_security))


# Planning case A, as the probe ran it: itemized deductions of a $38,000 property tax and $18,000 of
# mortgage interest. AGI 420,000 + 12,000 + 30,000 + 80,000 = 542,000. SALT cap 40,000 less 30% of
# (542,000 - 500,000) = 27,400; itemized 27,400 + 18,000 = 45,400 > 31,500; taxable 496,600.
# Preferential 30,000 + 80,000 = 110,000; ordinary 386,600, inside 206,700..394,600: bracket 24%.
# Ordinary tax 2,385 + 8,772 + 24,145 + 24% x 179,900 (43,176) = 78,478. Gains 15% x 110,000 = 16,500.
# Regular tax 94,978. AMT: AMTI 496,600 + 27,400 SALT = 524,000, less 137,000 = 387,000; 26% x 239,100 +
# 28% x 37,900 + 16,500 = 89,278, under the regular tax, so none.
# NIIT 3.8% x min(122,000, 542,000 - 250,000) = 4,636. Income tax 94,978 + 4,636 = 99,614, the plan's figure.
# Additional Medicare 0.9% x (420,000 - 250,000) = 1,530 (not in iitax).
_CASE_A_WAGES = unit(
    "A",
    "married_filing_jointly",
    (filer("A1", 45, wages="420000"), filer("A2", 45)),
    interest="12000",
    dividends="30000",
    qualified="30000",
    long="80000",
)
CASE_A = dataclasses.replace(_CASE_A_WAGES, state_local_taxes=D("38000"), mortgage_interest=D("18000"))

# Planning case B: single, 74. Provisional income 62,000 + 9,000 + 15,000 + 19,000 = 105,000; taxable Social
# Security min(85% x 71,000 + 4,500 = 64,850, 85% x 38,000 = 32,300) = 32,300. AGI 86,000 + 32,300 = 118,300.
# Deductions 15,750 + 2,000 + senior (6,000 - 6% x 43,300 = 3,402) = 21,152; taxable 97,148.
# Ordinary 97,148 - 24,000 = 73,148, inside 48,475..103,350: bracket 22%.
# Tax 1,192.50 + 4,386 + 22% x 24,673 (5,428.06) = 11,006.56, plus 15% x 24,000 = 3,600: 14,606.56.
CASE_B = unit(
    "B",
    "single",
    (filer("B1", 74, social_security="38000"),),
    dividends="9000",
    qualified="9000",
    long="15000",
    iras=(IraFlows("B1", ZERO, ZERO, D(62000), ZERO, ZERO, D(500000)),),
)

# Planning case C: AGI 210,000 + 2,000 - 3,000 (loss limit) = 209,000; taxable 177,500, all ordinary, inside
# 96,950..206,700: bracket 22%. Tax 2,385 + 8,772 + 22% x 80,550 (17,721) = 28,878.
CASE_C = unit(
    "C",
    "married_filing_jointly",
    (filer("C1", 38, wages="130000"), filer("C2", 36, wages="80000")),
    interest="2000",
    long="-9000",
)


def summary(
    case: TaxUnitFacts,
    *,
    agi: str,
    taxable: str,
    deductions: str,
    bracket: str,
    senior: str = "0",
    tax: str,
    niit: str = "0",
    medicare: str = "0",
    ira: str = "0",
    social_security: str = "0",
) -> TaxSummary:
    return TaxSummary(
        household_id=case.household_id,
        tax_unit_id=case.tax_unit_id,
        calculator="taxcalc",
        agi=D(agi),
        taxable_income=D(taxable),
        deductions=D(deductions),
        senior_deduction=D(senior),
        bracket=D(bracket),
        income_tax=D(tax),
        niit=D(niit),
        additional_medicare=D(medicare),
        taxable_ira=D(ira),
        taxable_social_security=D(social_security),
        carryforward_short=ZERO,
        carryforward_long=ZERO,
        ira_basis=(),
    )


def test_the_three_planning_cases_in_one_batch_in_order() -> None:
    result = crosscheck([CASE_A, CASE_B, CASE_C], {"A": ZERO, "B": D(62000), "C": ZERO})
    assert result == [
        summary(
            CASE_A,
            agi="542000",
            taxable="496600",
            deductions="45400",
            bracket="0.24",
            tax="99614",
            niit="4636",
            medicare="1530",
        ),
        summary(
            CASE_B,
            agi="118300",
            taxable="97148",
            deductions="21152",
            senior="3402",
            bracket="0.22",
            tax="14606.56",
            ira="62000",
            social_security="32300",
        ),
        summary(CASE_C, agi="209000", taxable="177500", deductions="31500", bracket="0.22", tax="28878"),
    ]


def test_every_figure_is_decimal_to_the_cent() -> None:
    (result,) = crosscheck([CASE_B], {"B": D(62000)})
    assert result.income_tax.as_tuple().exponent == -2
    assert all(type(getattr(result, name)) is Decimal for name in ("agi", "taxable_income", "niit", "bracket"))


def test_a_carried_in_loss_nets_against_this_years_gain() -> None:
    # Case C's couple, with a 5,000 long gain this year against a 9,000 long loss carried in: net -4,000,
    # limited to -3,000. The same AGI, taxable income and tax as case C.
    carried = unit(
        "C2",
        "married_filing_jointly",
        CASE_C.filers,
        interest="2000",
        long="5000",
        carry_long="9000",
    )
    assert crosscheck([carried], {"C2": ZERO}) == [
        summary(carried, agi="209000", taxable="177500", deductions="31500", bracket="0.22", tax="28878")
    ]


def test_a_short_carryover_cuts_the_gain_taxed_at_the_preferential_rate() -> None:
    # Single, 50: wages 60,000, long gain 10,000, short loss of 4,000 carried in. Net gain 6,000 (Schedule D
    # line 16), so AGI 66,000 and taxable 50,250. Net capital gain min(10,000, 6,000) = 6,000; ordinary 44,250,
    # under 48,475: bracket 12%. Tax 1,192.50 + 12% x 32,325 (3,879) = 5,071.50; gains: 4,100 at 0% (to
    # 48,350), 1,900 at 15% = 285. Total 5,356.50.
    single = unit("S", "single", (filer("S1", 50, wages="60000"),), long="10000", carry_short="4000")
    assert crosscheck([single], {"S": ZERO}) == [
        summary(single, agi="66000", taxable="50250", deductions="15750", bracket="0.12", tax="5356.50")
    ]


def test_head_of_household_uses_its_own_deduction_and_brackets() -> None:
    # Wages 100,000; taxable 100,000 - 23,625 = 76,375, inside 64,850..103,350: bracket 22%.
    # Tax 1,700 + 12% x 47,850 (5,742) + 22% x 11,525 (2,535.50) = 9,977.50.
    head = unit("H", "head_of_household", (filer("H1", 40, wages="100000"),))
    assert crosscheck([head], {"H": ZERO}) == [
        summary(head, agi="100000", taxable="76375", deductions="23625", bracket="0.22", tax="9977.50")
    ]


def test_income_at_the_top_of_a_bracket_takes_that_brackets_rate() -> None:
    # Single, wages 64,225: taxable 64,225 - 15,750 = 48,475, the top of the 12% bracket; its last dollar is
    # taxed at 12%. Tax 1,192.50 + 12% x 36,550 (4,386) = 5,578.50.
    edge = unit("E", "single", (filer("E1", 40, wages="64225"),))
    assert crosscheck([edge], {"E": ZERO}) == [
        summary(edge, agi="64225", taxable="48475", deductions="15750", bracket="0.12", tax="5578.50")
    ]


def test_no_units_gives_no_summaries() -> None:
    assert crosscheck([], {}) == []


def test_income_over_the_last_threshold_takes_the_top_rate() -> None:
    # Single, wages 1,000,000: taxable 984,250. Single brackets 24% to 197,300, 32% to 250,525, 35% to 626,350,
    # 37% above. Tax 1,192.50 + 4,386 + 12,072.50 + 22,548 + 17,032 + 131,538.75 + 37% x 357,900 (132,423)
    # = 321,192.75. AMT: the 88,100 exemption phases out entirely (25% x 373,650 over 626,350);
    # 26% x 239,100 + 28% x 760,900 = 275,218, under the regular tax. Additional Medicare 0.9% x 800,000.
    top = unit("T", "single", (filer("T1", 40, wages="1000000"),))
    assert crosscheck([top], {"T": ZERO}) == [
        summary(
            top, agi="1000000", taxable="984250", deductions="15750", bracket="0.37", tax="321192.75", medicare="7200"
        )
    ]


def test_a_separate_filer_s_salt_limit_is_halved_after_the_phase_down() -> None:
    # Reviewer B, slice 7 round 1. Married filing separately, wages 300,000, 40,000 of state and local taxes and
    # 20,000 of mortgage interest. 2025 Schedule A instructions, State and Local Tax Deduction Worksheet: line 1
    # 40,000; line 6 300,000 - 250,000 = 50,000; line 7 15,000; line 8 25,000; line 9 25,000; line 10 half,
    # 12,500. Itemized 32,500; taxable 267,500. Separate brackets: 1,192.50 + 4,386 + 12,072.50 + 22,548 +
    # 32% x 53,225 (17,032) + 35% x (267,500 - 250,525) (5,941.25) = 63,172.25. AMT: 280,000 - 68,500 = 211,500;
    # 26% x 119,550 + 28% x 91,950 = 56,829, under the regular tax. Additional Medicare 0.9% x 175,000 = 1,575.
    separate = dataclasses.replace(
        unit("M", "married_filing_separately", (filer("M1", 45, wages="300000"),)),
        state_local_taxes=D("40000"),
        mortgage_interest=D("20000"),
    )
    assert crosscheck([separate], {"M": ZERO}) == [
        summary(
            separate,
            agi="300000",
            taxable="267500",
            deductions="32500",
            bracket="0.35",
            tax="63172.25",
            medicare="1575",
        )
    ]
