"""Form 1040 lines 12 to 14: Schedule A or the standard deduction, and the 2025 senior deduction (Schedule 1-A,
Part V)."""

from dataclasses import dataclass
from decimal import Decimal

from casebook.model.money import cents
from casebook.model.tax import ZERO, Filer, TaxUnitFacts
from casebook.rules import Rules
from casebook.tax.engine.status import is_joint, is_married, is_separate, suffix

# 26 U.S.C. § 63(f)(1)(A) and § 151(d)(5)(C)(ii): the additional standard deduction and the senior deduction
# go to an individual who has attained age 65 before the close of the year. Not indexed.
SENIOR_AGE = 65


@dataclass(frozen=True)
class ScheduleA:
    state_local_taxes: Decimal  # line 5d: paid, before the cap
    salt_limit: Decimal  # the § 164(b)(6) and (7) limit after the phase-down
    salt_deduction: Decimal  # line 5e
    mortgage_interest: Decimal  # line 8a
    total: Decimal  # line 17


@dataclass(frozen=True)
class Deductions:
    schedule_a: ScheduleA
    standard: Decimal  # the standard deduction with the additional amounts for age 65
    itemized: bool
    deduction: Decimal  # Form 1040 line 12: the larger of the two
    senior: Decimal  # Schedule 1-A, Part V


def seniors(filers: tuple[Filer, ...]) -> int:
    return sum(1 for filer in filers if filer.age >= SENIOR_AGE)


def schedule_a(facts: TaxUnitFacts, magi: Decimal, rules: Rules) -> ScheduleA:
    """Line 5e by the 2025 State and Local Tax Deduction Worksheet: the $40,000 cap less 30% of modified AGI
    over the threshold (half the threshold for a separate filer), not below $10,000 (lines 1 to 9); a
    separate filer then takes half (line 10)."""
    separate = is_separate(facts.filing_status)
    threshold = rules.value("salt_phase_down_threshold_mfs" if separate else "salt_phase_down_threshold")
    reduced = rules.value("salt_cap") - rules.value("salt_phase_down_rate") * max(ZERO, magi - threshold)
    line_9 = max(rules.value("salt_floor"), reduced)
    limit = cents(line_9 * rules.value("salt_separate_share") if separate else line_9)
    salt = min(facts.state_local_taxes, limit)
    return ScheduleA(facts.state_local_taxes, limit, salt, facts.mortgage_interest, salt + facts.mortgage_interest)


def standard_deduction(facts: TaxUnitFacts, rules: Rules) -> Decimal:
    extra = rules.value(
        "additional_standard_deduction_married"
        if is_married(facts.filing_status)
        else "additional_standard_deduction_unmarried"
    )
    return rules.value(f"standard_deduction_{suffix(facts.filing_status)}") + extra * seniors(facts.filers)


def senior_deduction(facts: TaxUnitFacts, magi: Decimal, rules: Rules) -> Decimal:
    """Each qualified individual's amount is reduced by the rate times the whole excess (Schedule 1-A lines
    for you and your spouse); none on a separate return, § 151(d)(5)(C)(v)."""
    if is_separate(facts.filing_status):
        return ZERO
    threshold = rules.value(
        "senior_deduction_phaseout_joint" if is_joint(facts.filing_status) else "senior_deduction_phaseout_single"
    )
    reduction = cents(rules.value("senior_deduction_phaseout_rate") * max(ZERO, magi - threshold))
    return max(ZERO, rules.value("senior_deduction") - reduction) * seniors(facts.filers)


def deductions(facts: TaxUnitFacts, agi: Decimal, rules: Rules) -> Deductions:
    # The modified AGI of § 164(b)(7)(B) and § 151(d)(5)(C)(iii) adds back only foreign income exclusions,
    # which the book does not hold, so it is AGI.
    itemized = schedule_a(facts, agi, rules)
    standard = standard_deduction(facts, rules)
    itemizes = itemized.total > standard
    return Deductions(
        schedule_a=itemized,
        standard=standard,
        itemized=itemizes,
        deduction=itemized.total if itemizes else standard,
        senior=senior_deduction(facts, agi, rules),
    )
