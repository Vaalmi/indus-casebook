"""The in-house calculator: a tax unit's 2025 Form 1040 and the schedules and forms it triggers, from the facts.

The book's simplifications hold throughout: no dependents and no credits, no foreign tax, no adjustments to
income, no capital gain distributions, wages that are also Medicare wages. `income_tax` is the regular tax plus
the AMT plus the net investment income tax, to the cent; the Additional Medicare Tax is kept apart, as
Tax-Calculator keeps it in payroll tax.
"""

from dataclasses import dataclass
from decimal import Decimal

from casebook.model.tax import ZERO, TaxSummary, TaxUnitFacts
from casebook.rules import Rules, load_rules
from casebook.tax.engine.deductions import Deductions, deductions
from casebook.tax.engine.form_8606 import Form8606, form_8606
from casebook.tax.engine.schedule_d import ScheduleD, schedule_d, with_carryover
from casebook.tax.engine.social_security import SocialSecurityWorksheet, taxable_social_security
from casebook.tax.engine.status import EngineError, suffix
from casebook.tax.engine.surtaxes import Form8959, Form8960, form_8959, form_8960
from casebook.tax.engine.tax_computation import Form6251, QualifiedDividendsWorksheet, bracket, form_6251, regular_tax

CALCULATOR = "engine"

__all__ = ["CALCULATOR", "EngineError", "EngineResult", "Form1040", "compute"]


@dataclass(frozen=True)
class Form1040:
    wages: Decimal  # line 1z
    tax_exempt_interest: Decimal  # line 2a
    taxable_interest: Decimal  # line 2b
    qualified_dividends: Decimal  # line 3a
    ordinary_dividends: Decimal  # line 3b
    ira_distributions: Decimal  # line 4a: distributions, conversions, QCDs and inherited-IRA distributions
    taxable_ira: Decimal  # line 4b
    pensions: Decimal  # line 5a: 401(k) distributions
    taxable_pensions: Decimal  # line 5b
    social_security: Decimal  # line 6a
    taxable_social_security: Decimal  # line 6b
    capital_gain: Decimal  # line 7
    total_income: Decimal  # line 9
    agi: Decimal  # line 11
    deduction: Decimal  # line 12: standard or itemized
    senior_deduction: Decimal  # Schedule 1-A
    taxable_income: Decimal  # line 15
    tax: Decimal  # line 16: the regular tax
    amt: Decimal  # Schedule 2, line 1
    niit: Decimal  # Schedule 2: Form 8960
    additional_medicare: Decimal  # Schedule 2: Form 8959
    total_tax: Decimal  # line 24: all four
    withholding: Decimal  # line 25


@dataclass(frozen=True)
class EngineResult:
    summary: TaxSummary
    form_1040: Form1040
    form_8606: tuple[Form8606, ...]  # one per person in the facts' IRAs, in their order
    schedule_d: ScheduleD  # its carryover fields are the loss carried to 2026
    deductions: Deductions
    social_security: SocialSecurityWorksheet
    qualified_dividends_worksheet: QualifiedDividendsWorksheet
    form_6251: Form6251
    form_8960: Form8960
    form_8959: Form8959


def compute(facts: TaxUnitFacts, rules: Rules | None = None) -> EngineResult:
    rules = rules or load_rules()
    status = facts.filing_status
    suffix(status)  # an unknown status fails here, before any figure
    forms_8606 = tuple(form_8606(ira) for ira in facts.iras)
    taxable_ira = sum((form.taxable for form in forms_8606), facts.inherited_ira_distributions)
    capital = schedule_d(facts, rules)
    wages = sum((filer.wages for filer in facts.filers), ZERO)
    benefits = sum((filer.social_security for filer in facts.filers), ZERO)
    income_before_benefits = (
        wages
        + facts.taxable_interest
        + facts.ordinary_dividends
        + taxable_ira
        + facts.plan_distributions
        + capital.capital_gain
    )
    benefits_sheet = taxable_social_security(status, benefits, income_before_benefits, facts.tax_exempt_interest, rules)
    agi = income_before_benefits + benefits_sheet.taxable
    deducted = deductions(facts, agi, rules)
    before_floor = agi - deducted.deduction - deducted.senior
    taxable_income = max(ZERO, before_floor)
    # Adjusted taxable income adds back the § 151 deduction, the senior deduction (§ 1212(b)(2)(B)(ii)).
    capital = with_carryover(capital, before_floor + deducted.senior)
    worksheet = regular_tax(taxable_income, facts.qualified_dividends, capital.net_capital_gain, status, rules)
    amt = form_6251(
        agi,
        deducted.deduction,
        deducted.schedule_a.salt_deduction if deducted.itemized else deducted.standard,
        worksheet,
        status,
        rules,
    )
    niit = form_8960(facts.taxable_interest, facts.ordinary_dividends, capital.capital_gain, agi, status, rules)
    medicare = form_8959(wages, status, rules)
    income_tax = worksheet.line_25 + amt.line_11 + niit.line_17
    form_1040 = Form1040(
        wages=wages,
        tax_exempt_interest=facts.tax_exempt_interest,
        taxable_interest=facts.taxable_interest,
        qualified_dividends=facts.qualified_dividends,
        ordinary_dividends=facts.ordinary_dividends,
        ira_distributions=sum(
            (ira.distributions + ira.conversions + ira.qcd for ira in facts.iras), facts.inherited_ira_distributions
        ),
        taxable_ira=taxable_ira,
        pensions=facts.plan_distributions,
        taxable_pensions=facts.plan_distributions,
        social_security=benefits,
        taxable_social_security=benefits_sheet.taxable,
        capital_gain=capital.capital_gain,
        total_income=agi,
        agi=agi,
        deduction=deducted.deduction,
        senior_deduction=deducted.senior,
        taxable_income=taxable_income,
        tax=worksheet.line_25,
        amt=amt.line_11,
        niit=niit.line_17,
        additional_medicare=medicare.line_7,
        total_tax=income_tax + medicare.line_7,
        withholding=facts.federal_withholding,
    )
    summary = TaxSummary(
        household_id=facts.household_id,
        tax_unit_id=facts.tax_unit_id,
        calculator=CALCULATOR,
        agi=agi,
        taxable_income=taxable_income,
        deductions=deducted.deduction + deducted.senior,
        senior_deduction=deducted.senior,
        bracket=bracket(worksheet.line_5, status, rules),
        income_tax=income_tax,
        niit=niit.line_17,
        additional_medicare=medicare.line_7,
        taxable_ira=taxable_ira + facts.plan_distributions,
        taxable_social_security=benefits_sheet.taxable,
        carryforward_short=capital.carryover_short,
        carryforward_long=capital.carryover_long,
        ira_basis=tuple((form.person_id, form.line_14) for form in forms_8606),
    )
    return EngineResult(
        summary=summary,
        form_1040=form_1040,
        form_8606=forms_8606,
        schedule_d=capital,
        deductions=deducted,
        social_security=benefits_sheet,
        qualified_dividends_worksheet=worksheet,
        form_6251=amt,
        form_8960=niit,
        form_8959=medicare,
    )
