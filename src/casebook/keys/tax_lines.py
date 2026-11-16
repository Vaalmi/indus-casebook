"""The keys' own Form 8606 and capital loss carryover, written apart from the tax engine.

No outside calculator figures IRA basis or a capital loss carryover, so these are the second
implementation the engine is compared with. Each follows the 2025 form or worksheet line by line:
Form 8606 Part I and Part II, and the Capital Loss Carryover Worksheet in the 2025 Schedule D
instructions (line 21), which carries a 2025 loss to 2026.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from casebook.model.money import cents
from casebook.model.tax import ZERO, IraFlows, TaxUnitFacts
from casebook.rules import load_rules

# Form 8606 line 10 (and Pub. 590-B Worksheet 1-1, line 7): "a decimal rounded to at least three
# places. If the result is 1.000 or more, enter 1.000". The key rounds to exactly three, half-up.
LINE_10_PLACES = Decimal("0.001")
LINE_10_CAP = Decimal("1.000")
MARRIED_FILING_SEPARATELY = "married_filing_separately"


@dataclass(frozen=True)
class Form8606Lines:
    """One person's 2025 Form 8606, Parts I and II. A line the form says to skip is None."""

    person_id: str
    line_1: Decimal  # nondeductible contributions for 2025
    line_2: Decimal  # basis carried in from 2024
    line_3: Decimal
    line_4: Decimal | None  # contributions on line 1 made from 1 January to 15 April 2026
    line_5: Decimal | None
    line_6: Decimal | None  # value of all traditional, SEP and SIMPLE IRAs at 31 December 2025
    line_7: Decimal | None  # distributions, not conversions, not QCDs
    line_8: Decimal | None  # net amount converted to Roth IRAs
    line_9: Decimal | None
    line_10: Decimal | None
    line_11: Decimal | None  # nontaxable part of the conversions
    line_12: Decimal | None  # nontaxable part of the distributions
    line_13: Decimal | None
    line_14: Decimal  # basis carried to 2026
    line_15a: Decimal | None
    line_15b: Decimal | None  # qualified disaster distributions: none in the book
    line_15c: Decimal | None  # taxable distributions
    line_16: Decimal | None
    line_17: Decimal | None
    line_18: Decimal | None  # taxable conversions

    @property
    def taxable(self) -> Decimal:
        """What this form adds to Form 1040 line 4b: line 15c plus line 18."""
        return (self.line_15c or ZERO) + (self.line_18 or ZERO)

    @property
    def basis_carried(self) -> Decimal:
        return self.line_14


def _line_10(line_5: Decimal, line_9: Decimal) -> Decimal:
    return min((line_5 / line_9).quantize(LINE_10_PLACES, rounding=ROUND_HALF_UP), LINE_10_CAP)


def form_8606(flows: IraFlows) -> Form8606Lines:
    line_1 = flows.nondeductible_contributions
    line_2 = flows.basis_prior
    line_3 = line_1 + line_2
    # The form's question before line 4: with no distribution and no conversion, line 3 goes to
    # line 14 and the rest of Part I and all of Part II are left blank.
    if flows.distributions == ZERO and flows.conversions == ZERO:
        return Form8606Lines(
            person_id=flows.person_id,
            line_1=line_1,
            line_2=line_2,
            line_3=line_3,
            line_4=None,
            line_5=None,
            line_6=None,
            line_7=None,
            line_8=None,
            line_9=None,
            line_10=None,
            line_11=None,
            line_12=None,
            line_13=None,
            line_14=line_3,
            line_15a=None,
            line_15b=None,
            line_15c=None,
            line_16=None,
            line_17=None,
            line_18=None,
        )
    # The book does not record contributions made in 2026 for 2025, so line 4 is zero.
    line_4 = ZERO
    line_5 = line_3 - line_4
    line_6 = flows.year_end_value
    line_7 = flows.distributions
    line_8 = flows.conversions
    line_9 = line_6 + line_7 + line_8
    line_10 = _line_10(line_5, line_9)
    line_11 = cents(line_8 * line_10)
    line_12 = cents(line_7 * line_10)
    line_13 = line_11 + line_12
    line_14 = line_3 - line_13
    line_15a = line_7 - line_12
    line_15b = ZERO
    line_15c = line_15a - line_15b
    # Part II is completed only for a conversion; line 16 and 17 then come from lines 8 and 11.
    converted = line_8 != ZERO
    line_16 = line_8 if converted else None
    line_17 = line_11 if converted else None
    line_18 = line_8 - line_11 if converted else None
    return Form8606Lines(
        person_id=flows.person_id,
        line_1=line_1,
        line_2=line_2,
        line_3=line_3,
        line_4=line_4,
        line_5=line_5,
        line_6=line_6,
        line_7=line_7,
        line_8=line_8,
        line_9=line_9,
        line_10=line_10,
        line_11=line_11,
        line_12=line_12,
        line_13=line_13,
        line_14=line_14,
        line_15a=line_15a,
        line_15b=line_15b,
        line_15c=line_15c,
        line_16=line_16,
        line_17=line_17,
        line_18=line_18,
    )


def taxable_retirement(facts: TaxUnitFacts) -> Decimal:
    """The unit's taxable IRA and pension income (Form 1040 lines 4b and 5b): each person's Form 8606
    taxable amounts, plus 401(k) and inherited-IRA distributions. A QCD is never income."""
    ira = sum((form_8606(flows).taxable for flows in facts.iras), ZERO)
    return ira + facts.plan_distributions + facts.inherited_ira_distributions


def _loss_limit(filing_status: str) -> Decimal:
    rules = load_rules()
    if filing_status == MARRIED_FILING_SEPARATELY:
        return rules.value("capital_loss_limit_mfs")
    return rules.value("capital_loss_limit")


def capital_loss_carryover(
    facts: TaxUnitFacts, taxable_income: Decimal, section_151_deduction: Decimal
) -> tuple[Decimal, Decimal]:
    """The short-term and long-term capital loss carried to 2026, as positive amounts.

    `taxable_income` is the 2025 Form 1040 line 15 as it would be if a negative amount could be
    entered (Schedule D instructions, line 21): pass the figure before any floor at zero.
    `section_151_deduction` is the deduction allowed under § 151, which the worksheet's line 1 adds
    back (26 U.S.C. § 1212(b)(2)(B)(ii)): for 2025, the senior deduction of § 151(d)(5)(C).
    """
    schedule_d_7 = facts.short_term_gain - facts.carryforward_short
    schedule_d_15 = facts.long_term_gain - facts.carryforward_long
    schedule_d_16 = schedule_d_7 + schedule_d_15
    if schedule_d_16 >= ZERO:
        return ZERO, ZERO
    schedule_d_21 = max(schedule_d_16, -_loss_limit(facts.filing_status))

    line_1 = taxable_income + section_151_deduction
    line_2 = -schedule_d_21
    line_3 = max(line_1 + line_2, ZERO)
    line_4 = min(line_2, line_3)
    line_5 = -schedule_d_7 if schedule_d_7 < ZERO else ZERO
    short_carryover = ZERO
    if schedule_d_7 < ZERO:
        line_6 = max(schedule_d_15, ZERO)
        line_7 = line_4 + line_6
        short_carryover = max(line_5 - line_7, ZERO)
    long_carryover = ZERO
    if schedule_d_15 < ZERO:
        line_9 = -schedule_d_15
        line_10 = max(schedule_d_7, ZERO)
        line_11 = max(line_4 - line_5, ZERO)
        line_12 = line_10 + line_11
        long_carryover = max(line_9 - line_12, ZERO)
    return short_carryover, long_carryover
