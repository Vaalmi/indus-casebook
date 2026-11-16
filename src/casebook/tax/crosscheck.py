"""The second calculator: Tax-Calculator 6.9.1 on the tax-unit facts, its 2025 figures as a `TaxSummary`.

The only module that imports Tax-Calculator (docs/PLAN.md, import contract 3). Tax-Calculator works in
float, so `_run` is the one place a float exists: Decimal goes in, and every figure comes out as Decimal
rounded half-up to the cent.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from typing import Any

import pandas as pd
import taxcalc as tc

from casebook.model.money import cents
from casebook.model.tax import TAX_YEAR, ZERO, TaxSummary, TaxUnitFacts

CALCULATOR = "taxcalc"
# Tax-Calculator's MARS codes (records_variables.json): 1 single, 2 joint, 3 separate, 4 head of household.
MARS = {"single": 1, "married_filing_jointly": 2, "married_filing_separately": 3, "head_of_household": 4}
JOINT = MARS["married_filing_jointly"]
OUTPUTS = (
    "c00100",  # AGI
    "c04800",  # taxable income
    "dwks10",  # qualified dividends plus net capital gain (Sch D Tax Worksheet line 10)
    "iitax",  # income tax after credits, AMT and NIIT included
    "niit",
    "ptax_amc",  # Additional Medicare Tax
    "c02500",  # taxable Social Security
    "c04470",  # itemized deductions after the SALT cap
    "standard",  # standard deduction
    "senior_deduction",  # Schedule 1-A Part V
)
RATES = tuple(f"II_rt{n}" for n in range(1, 8))  # the seven ordinary rates
THRESHOLDS = tuple(f"II_brk{n}" for n in range(1, 7))  # the top of each of the first six brackets, by MARS

type Inputs = dict[str, int | Decimal]


@dataclass(frozen=True)
class Schedule:
    """Tax-Calculator's own 2025 ordinary brackets for one filing status."""

    thresholds: tuple[Decimal, ...]
    rates: tuple[Decimal, ...]

    def bracket(self, ordinary_taxable: Decimal) -> Decimal:
        """The rate on the last dollar of taxable ordinary income; the first rate when there is none."""
        for threshold, rate in zip(self.thresholds, self.rates, strict=False):
            if ordinary_taxable <= threshold:
                return rate
        return self.rates[-1]


def crosscheck(units: Sequence[TaxUnitFacts], taxable_ira: Mapping[str, Decimal]) -> list[TaxSummary]:
    """Tax-Calculator's summary for each unit, in order. `taxable_ira` maps each tax unit ID to its taxable
    IRA, 401(k) and inherited-IRA distributions together (Form 8606 from the keys)."""
    if not units:
        return []
    rows = [_inputs(n, unit, taxable_ira[unit.tax_unit_id]) for n, unit in enumerate(units, start=1)]
    figures, schedules = _run(rows)
    return [
        _summary(unit, row, schedules[MARS[unit.filing_status]], taxable_ira[unit.tax_unit_id])
        for unit, row in zip(units, figures, strict=True)
    ]


def _inputs(record_id: int, unit: TaxUnitFacts, taxable_ira: Decimal) -> Inputs:
    mars = MARS[unit.filing_status]
    head = unit.filers[0]
    spouse = unit.filers[1] if mars == JOINT else None
    spouse_wages = spouse.wages if spouse else ZERO
    return {
        "RECID": record_id,
        "FLPDYR": TAX_YEAR,
        "MARS": mars,
        "XTOT": len(unit.filers),  # the book has no dependents
        "age_head": head.age,
        "age_spouse": spouse.age if spouse else 0,
        "e00200": head.wages + spouse_wages,
        "e00200p": head.wages,
        "e00200s": spouse_wages,
        "e00300": unit.taxable_interest,
        "e00400": unit.tax_exempt_interest,
        "e00600": unit.ordinary_dividends,
        "e00650": unit.qualified_dividends,
        # Schedule D lines 6 and 14: the carryovers enter each column as a loss; Tax-Calculator applies the
        # loss limit itself.
        "p22250": unit.short_term_gain - unit.carryforward_short,
        "p23250": unit.long_term_gain - unit.carryforward_long,
        "e02400": sum((filer.social_security for filer in unit.filers), ZERO),
        "e01400": taxable_ira,
        # Schedule A: state and local taxes paid (the cap and its phase-down are Tax-Calculator's to
        # apply) and mortgage interest.
        "e18500": unit.state_local_taxes,
        "e19200": unit.mortgage_interest,
    }


@cache
def _current_law() -> tc.Policy:
    """Tax-Calculator's current-law policy, read from its parameter files once a process: building it is
    most of a batch's time, and every Calculator deep-copies the policy it is given."""
    return tc.Policy()


def _run(rows: Sequence[Inputs]) -> tuple[list[dict[str, Decimal]], dict[int, Schedule]]:
    """One batch through Tax-Calculator. Every float lives here, and only here."""

    def money(value: float) -> Decimal:
        return cents(Decimal(str(value)))

    frame = pd.DataFrame([{k: v if isinstance(v, int) else float(v) for k, v in row.items()} for row in rows])
    records = tc.Records(data=frame, start_year=TAX_YEAR, gfactors=None, weights=None)
    # The Calculator works on its own copy of the policy, set to the records' year, 2025.
    calc = tc.Calculator(policy=_current_law(), records=records)
    calc.calc_all()
    results = calc.dataframe(list(OUTPUTS))
    figures = [{name: money(results[name].iloc[n].item()) for name in OUTPUTS} for n in range(len(rows))]

    def parameter(name: str) -> Any:
        value = calc.policy_param(name)
        if value is None:
            raise ValueError(f"Tax-Calculator has no parameter {name}")
        return value

    rates = tuple(Decimal(str(parameter(name).item())) for name in RATES)
    by_status = [[money(v) for v in parameter(name).tolist()] for name in THRESHOLDS]
    schedules = {
        mars: Schedule(thresholds=tuple(column[mars - 1] for column in by_status), rates=rates)
        for mars in MARS.values()
    }
    return figures, schedules


def _summary(
    unit: TaxUnitFacts, figures: Mapping[str, Decimal], schedule: Schedule, taxable_ira: Decimal
) -> TaxSummary:
    taxable_income = figures["c04800"]
    ordinary_taxable = max(ZERO, taxable_income - figures["dwks10"])
    return TaxSummary(
        household_id=unit.household_id,
        tax_unit_id=unit.tax_unit_id,
        calculator=CALCULATOR,
        agi=figures["c00100"],
        taxable_income=taxable_income,
        bracket=schedule.bracket(ordinary_taxable),
        income_tax=figures["iitax"],
        niit=figures["niit"],
        additional_medicare=figures["ptax_amc"],
        taxable_ira=taxable_ira,
        taxable_social_security=figures["c02500"],
        # Tax-Calculator's taxable income before its floor at zero: AGI less these (calcfunctions.TaxInc).
        deductions=max(figures["c04470"], figures["standard"]) + figures["senior_deduction"],
        senior_deduction=figures["senior_deduction"],
        # Neither is Tax-Calculator's: the keys implementation is the second calculator for these.
        carryforward_short=ZERO,
        carryforward_long=ZERO,
        ira_basis=(),
    )
