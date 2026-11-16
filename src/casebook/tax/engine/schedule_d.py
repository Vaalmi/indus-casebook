"""Schedule D (2025) Part III netting, the loss limit, and the Capital Loss Carryover Worksheet that splits the
loss carried to 2026 into short and long term (Schedule D instructions; Pub. 550, Worksheet 4-1)."""

from dataclasses import dataclass, replace
from decimal import Decimal

from casebook.model.tax import ZERO, TaxUnitFacts
from casebook.rules import Rules
from casebook.tax.engine.status import is_separate


@dataclass(frozen=True)
class ScheduleD:
    short_term_gain: Decimal  # lines 1a to 5: 2025's net short-term gain or loss
    short_term_carryover: Decimal  # line 6, positive
    net_short_term: Decimal  # line 7
    long_term_gain: Decimal  # lines 8a to 13
    long_term_carryover: Decimal  # line 14, positive
    net_long_term: Decimal  # line 15
    net_gain: Decimal  # line 16
    loss_allowed: Decimal  # line 21 as a positive amount: the smaller of the line 16 loss and the limit
    capital_gain: Decimal  # Form 1040 line 7: the line 16 gain, or the line 21 loss as a negative
    net_capital_gain: Decimal  # lines 15 and 16 both gains: the smaller, for the Qualified Dividends worksheet
    carryover_short: Decimal  # worksheet line 8 a year on: short-term loss carried to 2026, positive
    carryover_long: Decimal  # worksheet line 13 a year on: long-term loss carried to 2026, positive


def schedule_d(facts: TaxUnitFacts, rules: Rules) -> ScheduleD:
    """Parts I to III, with the carryover to 2026 left at zero until `with_carryover` runs the worksheet."""
    net_short = facts.short_term_gain - facts.carryforward_short
    net_long = facts.long_term_gain - facts.carryforward_long
    net = net_short + net_long
    limit = rules.value("capital_loss_limit_mfs" if is_separate(facts.filing_status) else "capital_loss_limit")
    loss_allowed = min(-net, limit) if net < ZERO else ZERO
    return ScheduleD(
        short_term_gain=facts.short_term_gain,
        short_term_carryover=facts.carryforward_short,
        net_short_term=net_short,
        long_term_gain=facts.long_term_gain,
        long_term_carryover=facts.carryforward_long,
        net_long_term=net_long,
        net_gain=net,
        loss_allowed=loss_allowed,
        capital_gain=net if net >= ZERO else -loss_allowed,
        net_capital_gain=min(net_long, net) if net_long > ZERO and net > ZERO else ZERO,
        carryover_short=ZERO,
        carryover_long=ZERO,
    )


def with_carryover(schedule: ScheduleD, adjusted_taxable_income: Decimal) -> ScheduleD:
    """`adjusted_taxable_income` is the worksheet's line 1: taxable income before its floor at zero ("If the
    amount would have been a loss ..., enclose the amount in parentheses"), with the deduction allowed under
    § 151 added back (§ 1212(b)(2)(B)(ii)), which for 2025 is the senior deduction (§ 151(d)(5)(C)). No net
    loss on line 16, no carryover."""
    if schedule.net_gain >= ZERO:
        return schedule
    short, long = carryover(
        adjusted_taxable_income, schedule.loss_allowed, schedule.net_short_term, schedule.net_long_term
    )
    return replace(schedule, carryover_short=short, carryover_long=long)


def carryover(
    taxable_income: Decimal, loss_allowed: Decimal, net_short: Decimal, net_long: Decimal
) -> tuple[Decimal, Decimal]:
    """The Capital Loss Carryover Worksheet, lines 1 to 13, run on this year's return."""
    line_2 = loss_allowed
    line_3 = max(ZERO, taxable_income + line_2)
    line_4 = min(line_2, line_3)
    line_5 = -net_short if net_short < ZERO else ZERO
    line_6 = max(ZERO, net_long)
    line_8 = max(ZERO, line_5 - (line_4 + line_6))
    if net_long >= ZERO:
        return line_8, ZERO
    line_9 = -net_long
    line_10 = max(ZERO, net_short)
    line_11 = max(ZERO, line_4 - line_5)
    line_13 = max(ZERO, line_9 - (line_10 + line_11))
    return line_8, line_13
