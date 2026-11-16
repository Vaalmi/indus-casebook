"""The net investment income tax (Form 8960) and the Additional Medicare Tax (Form 8959), 2025."""

from dataclasses import dataclass
from decimal import Decimal

from casebook.model.money import cents
from casebook.model.tax import ZERO
from casebook.rules import Rules
from casebook.tax.engine.status import suffix


@dataclass(frozen=True)
class Form8960:
    line_1: Decimal  # taxable interest
    line_2: Decimal  # ordinary dividends
    line_5a: Decimal  # net gain or loss, Form 1040 line 7 (the loss already limited)
    line_8: Decimal
    line_12: Decimal  # net investment income
    line_13: Decimal  # modified AGI: AGI, the book having no foreign income exclusion
    line_14: Decimal  # threshold
    line_16: Decimal
    line_17: Decimal  # the tax


@dataclass(frozen=True)
class Form8959:
    line_1: Decimal  # Medicare wages, W-2 box 5, both spouses
    line_5: Decimal  # threshold
    line_6: Decimal
    line_7: Decimal  # the tax (the book has no self-employment or RRTA income, so also line 18)


def form_8960(
    interest: Decimal, dividends: Decimal, capital_gain: Decimal, agi: Decimal, filing_status: str, rules: Rules
) -> Form8960:
    """IRA, plan and Social Security income are not investment income (§ 1411(c)(5)), so they stay out."""
    line_8 = interest + dividends + capital_gain
    line_12 = max(ZERO, line_8)
    threshold = rules.value(f"niit_threshold_{suffix(filing_status)}")
    line_16 = min(line_12, max(ZERO, agi - threshold))
    return Form8960(
        line_1=interest,
        line_2=dividends,
        line_5a=capital_gain,
        line_8=line_8,
        line_12=line_12,
        line_13=agi,
        line_14=threshold,
        line_16=line_16,
        line_17=cents(line_16 * rules.value("niit_rate")),
    )


def form_8959(medicare_wages: Decimal, filing_status: str, rules: Rules) -> Form8959:
    threshold = rules.value(f"additional_medicare_threshold_{suffix(filing_status)}")
    line_6 = max(ZERO, medicare_wages - threshold)
    return Form8959(medicare_wages, threshold, line_6, cents(line_6 * rules.value("additional_medicare_rate")))
