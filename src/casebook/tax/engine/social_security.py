"""Taxable Social Security: the Social Security Benefits Worksheet (Form 1040 instructions, 2025; Pub. 915,
Worksheet 1), under 26 U.S.C. § 86."""

from dataclasses import dataclass
from decimal import Decimal

from casebook.model.money import cents
from casebook.model.tax import ZERO
from casebook.rules import Rules
from casebook.tax.engine.status import EngineError, is_joint, is_separate

# § 86(a)(1)(A) and (a)(2)(A)(ii): one-half of the benefits; § 86(a)(2)(A)(i) and (a)(2)(B): 85 percent.
# The statute's own fractions, not indexed and not in the rules table.
HALF = Decimal("0.5")
EIGHTY_FIVE_PERCENT = Decimal("0.85")


@dataclass(frozen=True)
class SocialSecurityWorksheet:
    line_1: Decimal  # benefits, SSA-1099 box 5
    line_2: Decimal
    line_3: Decimal  # Form 1040 lines 1z, 2b, 3b, 4b, 5b, 7 and 8
    line_4: Decimal  # tax-exempt interest, Form 1040 line 2a
    line_5: Decimal
    line_8: Decimal  # base amount
    line_10: Decimal  # adjusted base amount less base amount
    taxable: Decimal  # line 18, Form 1040 line 6b


def taxable_social_security(
    filing_status: str, benefits: Decimal, other_income: Decimal, tax_exempt_interest: Decimal, rules: Rules
) -> SocialSecurityWorksheet:
    if is_separate(filing_status) and benefits > ZERO:
        # § 86(c)(1)(C): the base amount is zero if the separate filer lived with the spouse at any time in the
        # year, the single amounts if not. The facts don't say which.
        raise EngineError(
            "a married filer filing separately with Social Security: the facts don't say whether they lived apart"
        )
    key = "mfj" if is_joint(filing_status) else "single"
    base = rules.value(f"social_security_base_{key}")
    adjusted_base = rules.value(f"social_security_adjusted_base_{key}")
    line_2 = cents(benefits * HALF)
    line_5 = line_2 + other_income + tax_exempt_interest
    line_7 = line_5  # line 6, Schedule 1 adjustments: none in the book
    line_9 = max(ZERO, line_7 - base)
    line_10 = adjusted_base - base
    line_11 = max(ZERO, line_9 - line_10)
    line_13 = cents(min(line_9, line_10) * HALF)
    line_14 = min(line_2, line_13)
    line_16 = line_14 + cents(line_11 * EIGHTY_FIVE_PERCENT)
    line_17 = cents(benefits * EIGHTY_FIVE_PERCENT)
    return SocialSecurityWorksheet(
        line_1=benefits,
        line_2=line_2,
        line_3=other_income,
        line_4=tax_exempt_interest,
        line_5=line_5,
        line_8=base,
        line_10=line_10,
        taxable=min(line_16, line_17) if line_9 > ZERO else ZERO,
    )
