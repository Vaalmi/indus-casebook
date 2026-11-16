"""The regular tax (the rate schedule and the Qualified Dividends and Capital Gain Tax Worksheet), the bracket,
and the alternative minimum tax (Form 6251).

The rate schedule applies to every taxable income, never the IRS Tax Table: Tax-Calculator does the same, and
the table's $50 rows differ from the schedule by up to a few dollars below $100,000.
"""

from dataclasses import dataclass
from decimal import Decimal

from casebook.model.money import cents
from casebook.model.tax import ZERO
from casebook.rules import Rules
from casebook.tax.engine.status import is_separate, suffix

BASIS_POINTS = Decimal(10000)


def schedule(filing_status: str, rules: Rules) -> list[tuple[Decimal, Decimal]]:
    """(rate, start) pairs from the lowest rate up: each rate applies to taxable income over its start."""
    table = rules.tables[f"brackets_{suffix(filing_status)}"]
    return sorted((Decimal(points) / BASIS_POINTS, start) for points, start in table.values.items())


def rate_schedule_tax(amount: Decimal, filing_status: str, rules: Rules) -> Decimal:
    rows = schedule(filing_status, rules)
    tax = ZERO
    for (rate, start), (_, end) in zip(rows, [*rows[1:], (ZERO, amount)], strict=True):
        if amount > start:
            tax += rate * (min(amount, end) - start)
    return cents(tax)


def bracket(ordinary_income: Decimal, filing_status: str, rules: Rules) -> Decimal:
    """The rate on the last dollar of taxable ordinary income: income exactly at a bracket's top takes that
    bracket's rate, and none at all takes the lowest."""
    rows = schedule(filing_status, rules)
    return max((rate for rate, start in rows if ordinary_income > start), default=rows[0][0])


@dataclass(frozen=True)
class QualifiedDividendsWorksheet:
    """The Qualified Dividends and Capital Gain Tax Worksheet (Form 1040 instructions, 2025), lines 1 to 25."""

    line_1: Decimal  # taxable income
    line_2: Decimal  # qualified dividends
    line_3: Decimal  # net capital gain
    line_4: Decimal
    line_5: Decimal  # taxable ordinary income
    line_9: Decimal  # taxed at 0 percent
    line_17: Decimal  # taxed at 15 percent
    line_18: Decimal
    line_20: Decimal  # taxed at 20 percent
    line_21: Decimal
    line_22: Decimal  # rate-schedule tax on line 5
    line_23: Decimal
    line_24: Decimal  # rate-schedule tax on line 1
    line_25: Decimal  # the tax


def regular_tax(
    taxable_income: Decimal, qualified_dividends: Decimal, net_capital_gain: Decimal, filing_status: str, rules: Rules
) -> QualifiedDividendsWorksheet:
    """With no qualified dividends or net capital gain the worksheet reduces to the rate schedule on line 1."""
    key = suffix(filing_status)
    line_4 = qualified_dividends + net_capital_gain
    line_5 = max(ZERO, taxable_income - line_4)
    line_7 = min(taxable_income, rules.value(f"capital_gain_0_ceiling_{key}"))
    line_9 = line_7 - min(line_5, line_7)
    line_10 = min(taxable_income, line_4)
    line_12 = line_10 - line_9
    line_14 = min(taxable_income, rules.value(f"capital_gain_15_ceiling_{key}"))
    line_16 = max(ZERO, line_14 - (line_5 + line_9))
    line_17 = min(line_12, line_16)
    line_18 = cents(line_17 * rules.value("capital_gain_rate_15"))
    line_20 = line_10 - (line_9 + line_17)
    line_21 = cents(line_20 * rules.value("capital_gain_rate_20"))
    line_22 = rate_schedule_tax(line_5, filing_status, rules)
    line_23 = line_18 + line_21 + line_22
    line_24 = rate_schedule_tax(taxable_income, filing_status, rules)
    return QualifiedDividendsWorksheet(
        line_1=taxable_income,
        line_2=qualified_dividends,
        line_3=net_capital_gain,
        line_4=line_4,
        line_5=line_5,
        line_9=line_9,
        line_17=line_17,
        line_18=line_18,
        line_20=line_20,
        line_21=line_21,
        line_22=line_22,
        line_23=line_23,
        line_24=line_24,
        line_25=min(line_23, line_24),
    )


@dataclass(frozen=True)
class Form6251:
    line_1a: Decimal  # Form 1040 line 14 less the senior deduction, which the AMT allows
    line_1b: Decimal  # Form 1040 line 11 less line 1a
    line_2a: Decimal  # the standard deduction, or Schedule A's taxes for an itemizer
    line_4: Decimal  # alternative minimum taxable income
    line_5: Decimal  # exemption after the phase-out
    line_6: Decimal
    line_7: Decimal  # tentative minimum tax (no AMT foreign tax credit, so also line 9)
    line_10: Decimal  # regular tax
    line_11: Decimal  # alternative minimum tax


def amt_rate_tax(amount: Decimal, filing_status: str, rules: Rules) -> Decimal:
    rate_break = rules.value("amt_rate_break_mfs" if is_separate(filing_status) else "amt_rate_break")
    low = rules.value("amt_rate_low") * min(amount, rate_break)
    high = rules.value("amt_rate_high") * max(ZERO, amount - rate_break)
    return cents(low + high)


def form_6251(
    agi: Decimal,
    deduction_other_than_senior: Decimal,
    add_back: Decimal,
    worksheet: QualifiedDividendsWorksheet,
    filing_status: str,
    rules: Rules,
) -> Form6251:
    """The book has no preferences or adjustments beyond line 2a. `add_back` is the standard deduction for a
    non-itemizer and Schedule A's state and local taxes for an itemizer (§ 56(b)(1)(A)(ii) and (E))."""
    key = suffix(filing_status)
    line_1a = deduction_other_than_senior
    line_1b = agi - line_1a
    line_4 = line_1b + add_back
    exemption = rules.value(f"amt_exemption_{key}")
    phaseout = rules.value(f"amt_phaseout_{key}")
    rate = rules.value("amt_phaseout_rate")
    if is_separate(filing_status):
        # § 55(d)(2), last sentence: a separate filer adds the lesser of the exemption or the phase-out rate
        # times AMTI over the point where the exemption is gone.
        line_4 += cents(min(exemption, rate * max(ZERO, line_4 - (phaseout + exemption / rate))))
    line_5 = max(ZERO, exemption - cents(rate * max(ZERO, line_4 - phaseout)))
    line_6 = max(ZERO, line_4 - line_5)
    line_7 = _tentative_tax(line_6, worksheet, filing_status, rules)
    return Form6251(
        line_1a=line_1a,
        line_1b=line_1b,
        line_2a=add_back,
        line_4=line_4,
        line_5=line_5,
        line_6=line_6,
        line_7=line_7,
        line_10=worksheet.line_25,
        line_11=max(ZERO, line_7 - worksheet.line_25),
    )


def _tentative_tax(
    line_6: Decimal, worksheet: QualifiedDividendsWorksheet, filing_status: str, rules: Rules
) -> Decimal:
    """Line 7: the flat 26 and 28 percent tax, or Part III (lines 12 to 40) when the worksheet has qualified
    dividends or net capital gain. No unrecaptured section 1250 gain in the book, so lines 14 and 35 to 37
    are zero."""
    flat = amt_rate_tax(line_6, filing_status, rules)
    if worksheet.line_4 <= ZERO:
        return flat
    key = suffix(filing_status)
    line_13 = worksheet.line_4
    line_16 = min(line_6, line_13)
    line_18 = amt_rate_tax(line_6 - line_16, filing_status, rules)
    line_21 = max(ZERO, rules.value(f"capital_gain_0_ceiling_{key}") - worksheet.line_5)
    line_22 = min(line_6, line_13)
    line_23 = min(line_21, line_22)
    line_24 = line_22 - line_23
    line_28 = line_21 + worksheet.line_5  # line 26 is line 21; line 27 is the worksheet's line 5
    line_29 = max(ZERO, rules.value(f"capital_gain_15_ceiling_{key}") - line_28)
    line_30 = min(line_24, line_29)
    line_31 = cents(line_30 * rules.value("capital_gain_rate_15"))
    line_33 = line_22 - (line_23 + line_30)
    line_34 = cents(line_33 * rules.value("capital_gain_rate_20"))
    return min(line_18 + line_31 + line_34, flat)
