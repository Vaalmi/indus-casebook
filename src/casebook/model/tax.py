"""A tax unit's 2025 facts, and the tax summary the calculators reach from them.

The facts are what happened (the sealed event log and the household's records), not what a
custodian's records say: a planted basis error or a miscoded distribution does not change the tax
the household owes. `tax/facts.py` gathers them; the in-house engine (`tax/engine/`) and
Tax-Calculator (`tax/crosscheck.py`) each compute a summary from them, and the two must agree.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from casebook.model.money import cents

TAX_YEAR = 2025
FILING_STATUSES = ("single", "married_filing_jointly", "married_filing_separately", "head_of_household")
ZERO = Decimal(0)


@dataclass(frozen=True)
class Filer:
    """One person on the return: the primary filer, then the spouse on a joint return."""

    person_id: str
    age: int  # for the year's age tests: `age_for_the_year`
    wages: Decimal  # W-2 box 1, and box 5 (Medicare wages): the book has no pre-tax deferrals
    social_security: Decimal  # SSA-1099 box 5, net benefits for the year


@dataclass(frozen=True)
class IraFlows:
    """One person's traditional IRAs in the tax year: what Form 8606 Part I reads."""

    person_id: str
    basis_prior: Decimal  # line 2: after-tax basis carried in from the prior return
    nondeductible_contributions: Decimal  # line 1
    distributions: Decimal  # line 7: gross distributions, not conversions, not QCDs
    conversions: Decimal  # line 8: net amount converted to Roth IRAs
    qcd: Decimal  # paid directly to charity: excluded from income, not on line 7
    year_end_value: Decimal  # line 6: all the person's traditional, SEP and SIMPLE IRAs at 31 December


@dataclass(frozen=True)
class TaxUnitFacts:
    household_id: str
    tax_unit_id: str
    filing_status: str
    filers: tuple[Filer, ...]
    taxable_interest: Decimal
    tax_exempt_interest: Decimal  # municipal bond fund dividends (1099-DIV box 12)
    ordinary_dividends: Decimal  # 1099-DIV box 1a, qualified included
    qualified_dividends: Decimal  # 1099-DIV box 1b
    short_term_gain: Decimal  # net short-term gain or loss realized in 2025, true basis, wash sales applied
    long_term_gain: Decimal  # net long-term gain or loss, likewise
    carryforward_short: Decimal  # capital loss carried in from 2024, as a positive amount
    carryforward_long: Decimal
    iras: tuple[IraFlows, ...]
    plan_distributions: Decimal  # 401(k) distributions, fully taxable (no after-tax money in the book)
    inherited_ira_distributions: Decimal  # fully taxable (the decedents had no basis)
    federal_withholding: Decimal  # on W-2s and 1099-Rs; not part of the liability
    # Schedule A's inputs. The book's households hold none, so they take the standard deduction;
    # the planning probe's case A itemizes, and both calculators must handle it.
    state_local_taxes: Decimal = ZERO  # income and real estate taxes paid, before the SALT cap
    mortgage_interest: Decimal = ZERO


@dataclass(frozen=True)
class TaxSummary:
    """What the spec's summary holds, from one calculator: income, bracket, net investment income
    tax, loss carryforwards and IRA basis, with the figures between them."""

    household_id: str
    tax_unit_id: str
    calculator: str
    agi: Decimal  # "income"
    taxable_income: Decimal  # AGI less deductions, floored at zero
    deductions: Decimal  # the larger of standard and itemized, plus the senior deduction (Schedule 1-A)
    senior_deduction: Decimal  # Schedule 1-A Part V: a § 151 deduction, added back for the loss carryover
    bracket: Decimal  # the marginal ordinary rate on taxable ordinary income, e.g. 0.24
    income_tax: Decimal  # tax after credits, AMT and NIIT included (Tax-Calculator's iitax)
    niit: Decimal
    additional_medicare: Decimal
    taxable_ira: Decimal  # IRA, inherited-IRA and 401(k) distributions together: Form 1040 lines 4b and 5b
    taxable_social_security: Decimal
    carryforward_short: Decimal  # capital loss carried to 2026, positive
    carryforward_long: Decimal
    ira_basis: tuple[tuple[str, Decimal], ...]  # each person's basis carried to 2026 (Form 8606 line 14)


def long_term(acquired: date, sold: date) -> bool:
    """Held more than one year (26 U.S.C. § 1222(3)), counted by calendar months from the day after
    acquisition (Rev. Rul. 66-7): sold after the anniversary; a lot bought on 29 February is
    long-term from 1 March of the next year."""
    year = acquired.year + 1
    anniversary = date(year, acquired.month, min(acquired.day, calendar.monthrange(year, acquired.month)[1]))
    return sold > anniversary


QUALIFIED, ORDINARY, EXEMPT = "qualified", "ordinary", "exempt"


def dividend_character(alias: str) -> str:
    """How a security's dividends are taxed in the book, from its invented name: a municipal bond
    fund pays exempt-interest dividends, other bond and inflation-protected funds ordinary
    dividends, and every equity fund and stock qualified dividends (the book's simplification: no
    REIT's dividends are split out). The 1099-DIV and the tax facts both read it from here."""
    if "Muni" in alias or "Tax-Exempt" in alias:
        return EXEMPT
    if any(word in alias for word in ("Bond", "Inflation")):
        return ORDINARY
    return QUALIFIED


def age_for_the_year(born: date, died: date | None) -> int:
    """The age the year's age tests read (65 for the additional standard deduction and the senior
    deduction): the age reached by 31 December, or by the day of death for someone who died in the year,
    counting a birthday as reached the day before it (Pub. 501, "Age"; "Death of taxpayer")."""
    end = date(TAX_YEAR, 12, 31)
    last = min(end, died) if died is not None else end
    day = last + timedelta(days=1)
    return day.year - born.year - ((day.month, day.day) < (born.month, born.day))


def _money(value: Decimal) -> str:
    return format(value, "f")


def facts_to_dict(facts: TaxUnitFacts) -> dict[str, object]:
    return {
        "household_id": facts.household_id,
        "tax_unit_id": facts.tax_unit_id,
        "filing_status": facts.filing_status,
        "filers": [
            {
                "person_id": f.person_id,
                "age": f.age,
                "wages": _money(f.wages),
                "social_security": _money(f.social_security),
            }
            for f in facts.filers
        ],
        "iras": [
            {
                "person_id": i.person_id,
                "basis_prior": _money(i.basis_prior),
                "nondeductible_contributions": _money(i.nondeductible_contributions),
                "distributions": _money(i.distributions),
                "conversions": _money(i.conversions),
                "qcd": _money(i.qcd),
                "year_end_value": _money(i.year_end_value),
            }
            for i in facts.iras
        ],
        **{
            name: _money(getattr(facts, name))
            for name in (
                "taxable_interest",
                "tax_exempt_interest",
                "ordinary_dividends",
                "qualified_dividends",
                "short_term_gain",
                "long_term_gain",
                "carryforward_short",
                "carryforward_long",
                "plan_distributions",
                "inherited_ira_distributions",
                "federal_withholding",
                "state_local_taxes",
                "mortgage_interest",
            )
        },
    }


def parse_facts(raw: dict[str, Any]) -> TaxUnitFacts:
    money = {
        name: Decimal(str(raw[name]))
        for name in (
            "taxable_interest",
            "tax_exempt_interest",
            "ordinary_dividends",
            "qualified_dividends",
            "short_term_gain",
            "long_term_gain",
            "carryforward_short",
            "carryforward_long",
            "plan_distributions",
            "inherited_ira_distributions",
            "federal_withholding",
            "state_local_taxes",
            "mortgage_interest",
        )
    }
    return TaxUnitFacts(
        household_id=str(raw["household_id"]),
        tax_unit_id=str(raw["tax_unit_id"]),
        filing_status=str(raw["filing_status"]),
        filers=tuple(
            Filer(str(f["person_id"]), int(f["age"]), Decimal(str(f["wages"])), Decimal(str(f["social_security"])))
            for f in raw["filers"]
        ),
        iras=tuple(
            IraFlows(
                str(i["person_id"]),
                Decimal(str(i["basis_prior"])),
                Decimal(str(i["nondeductible_contributions"])),
                Decimal(str(i["distributions"])),
                Decimal(str(i["conversions"])),
                Decimal(str(i["qcd"])),
                Decimal(str(i["year_end_value"])),
            )
            for i in raw["iras"]
        ),
        **money,
    )


SUMMARY_MONEY = (
    "agi",
    "taxable_income",
    "deductions",
    "senior_deduction",
    "bracket",
    "income_tax",
    "niit",
    "additional_medicare",
    "taxable_ira",
    "taxable_social_security",
    "carryforward_short",
    "carryforward_long",
)


def summary_to_dict(summary: TaxSummary) -> dict[str, object]:
    return {
        "household_id": summary.household_id,
        "tax_unit_id": summary.tax_unit_id,
        "calculator": summary.calculator,
        # Every amount to the cent; the bracket is a rate.
        **{
            name: _money(getattr(summary, name) if name == "bracket" else cents(getattr(summary, name)))
            for name in SUMMARY_MONEY
        },
        "ira_basis": [{"person_id": p, "basis": _money(cents(b))} for p, b in summary.ira_basis],
    }


def parse_summary(raw: dict[str, Any]) -> TaxSummary:
    return TaxSummary(
        household_id=str(raw["household_id"]),
        tax_unit_id=str(raw["tax_unit_id"]),
        calculator=str(raw["calculator"]),
        **{name: Decimal(str(raw[name])) for name in SUMMARY_MONEY},
        ira_basis=tuple((str(b["person_id"]), Decimal(str(b["basis"]))) for b in raw["ira_basis"]),
    )
