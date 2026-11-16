"""Form 8606 (2025), Parts I and II, for one person's traditional IRAs."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from casebook.model.money import cents
from casebook.model.tax import ZERO, IraFlows

# Line 10: "Enter the result as a decimal rounded to at least 3 places. If the result is 1.000 or more, enter
# 1.000" (Form 8606 (2025), line 10). The book rounds to exactly three places, half up.
RATIO_PLACES = Decimal("0.001")
ONE = Decimal(1)


@dataclass(frozen=True)
class Form8606:
    """Every line of Parts I and II. Lines 6 to 13 are zero when the person took no distribution and made no
    conversion: the instructions then skip to line 14."""

    person_id: str
    line_1: Decimal  # nondeductible contributions for 2025
    line_2: Decimal  # basis from the prior year
    line_3: Decimal
    line_4: Decimal  # contributions made 1 January to 15 April 2026: none in the book
    line_5: Decimal
    line_6: Decimal  # value of all traditional, SEP and SIMPLE IRAs at 31 December 2025
    line_7: Decimal  # distributions, not conversions or QCDs
    line_8: Decimal  # net amount converted to Roth IRAs
    line_9: Decimal
    line_10: Decimal  # the nontaxable fraction, three places
    line_11: Decimal  # nontaxable part of the conversions
    line_12: Decimal  # nontaxable part of the distributions
    line_13: Decimal
    line_14: Decimal  # basis carried to 2026
    line_15a: Decimal
    line_15b: Decimal  # qualified disaster distributions: none in the book
    line_15c: Decimal  # taxable distributions
    line_16: Decimal
    line_17: Decimal
    line_18: Decimal  # taxable conversions

    @property
    def taxable(self) -> Decimal:
        """What goes on Form 1040 line 4b from this person's IRAs: lines 15c and 18."""
        return self.line_15c + self.line_18


def form_8606(ira: IraFlows) -> Form8606:
    line_3 = ira.nondeductible_contributions + ira.basis_prior
    line_5 = line_3  # line 4 is zero
    moved = ira.distributions + ira.conversions
    if moved == ZERO:
        line_6 = line_9 = line_10 = ZERO
    else:
        line_6 = ira.year_end_value
        line_9 = line_6 + moved
        line_10 = min(ONE, (line_5 / line_9).quantize(RATIO_PLACES, rounding=ROUND_HALF_UP))
    line_11 = cents(ira.conversions * line_10)
    line_12 = cents(ira.distributions * line_10)
    line_13 = line_11 + line_12
    line_15a = ira.distributions - line_12
    return Form8606(
        person_id=ira.person_id,
        line_1=ira.nondeductible_contributions,
        line_2=ira.basis_prior,
        line_3=line_3,
        line_4=ZERO,
        line_5=line_5,
        line_6=line_6,
        line_7=ira.distributions,
        line_8=ira.conversions,
        line_9=line_9,
        line_10=line_10,
        line_11=line_11,
        line_12=line_12,
        line_13=line_13,
        line_14=line_3 - line_13,
        line_15a=line_15a,
        line_15b=ZERO,
        line_15c=line_15a,
        line_16=ira.conversions,
        line_17=line_11,
        line_18=ira.conversions - line_11,
    )
