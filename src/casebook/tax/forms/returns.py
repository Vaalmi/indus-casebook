"""What goes on each line of a tax unit's 2025 return, and which schedules and forms its facts trigger.

The figures are the in-house engine's (`tax/engine`); the detail behind them, each lot sold and each
dividend payer, is the tax facts'. Every schedule and form after the 1040 is filled only where the facts
trigger it (docs/PLAN.md, U5). Keys are each form's own line labels, as `tax/forms` maps them.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal

from casebook.model.household import Household, Person
from casebook.model.money import cents
from casebook.model.tax import TAX_YEAR, ZERO, Sale, TaxUnitFacts, age_for_the_year
from casebook.rules import Rules, load_rules
from casebook.tax.engine import EngineResult
from casebook.tax.engine.form_8606 import Form8606

type Value = str | bool

# Form 1040 Schedule B instructions: Schedule B is required with over $1,500 of taxable interest or of
# ordinary dividends.
SCHEDULE_B_OVER = Decimal(1500)
# 26 U.S.C. § 63(f)(1)(A) and § 151(d)(5)(C)(ii): the age-65 boxes and the senior deduction.
SENIOR_AGE = 65
# Form 8949: eleven rows a part a page (2025 form).
ROWS_A_PAGE = 11
STATUS_KEY = {
    "single": "status_single",
    "married_filing_jointly": "status_mfj",
    "married_filing_separately": "status_mfs",
    "head_of_household": "status_hoh",
}


FORM_ORDER = (
    "f1040",
    "f1040s1",
    "f1040s1a",
    "f1040s2",
    "f1040s3",
    "f1040sa",
    "f1040sb",
    "f1040sd",
    "f8949",
    "f8606",
    "f8960",
    "f8959",
)


@dataclass(frozen=True)
class FilledForm:
    """One PDF of a return: the form, the file it is written to, and its values by line."""

    form: str  # the `tax/forms` form ID, e.g. "f1040"
    file: str  # e.g. "f1040.pdf", "f8606-P-1204-2.pdf", "f8949-A-1.pdf"
    values: dict[str, Value]


def amount(value: Decimal) -> str:
    """An amount as the return shows it: to the cent, with thousands separators, a loss in parentheses."""
    shown = f"{abs(cents(value)):,.2f}"
    return f"({shown})" if value < 0 else shown


def _names(person: Person) -> tuple[str, str]:
    first, _, last = person.name.partition(" ")
    return first, last


def _on_return(values: dict[str, Value], **lines: Decimal) -> None:
    """Set each line, the way a preparer leaves a line that does not apply blank: zero amounts are left off."""
    for line, value in lines.items():
        if value != ZERO:
            values[line.removeprefix("l_")] = amount(value)


def needs_schedule_b(facts: TaxUnitFacts) -> bool:
    return facts.taxable_interest > SCHEDULE_B_OVER or facts.ordinary_dividends > SCHEDULE_B_OVER


def needs_schedule_d(facts: TaxUnitFacts) -> bool:
    return bool(facts.sales) or facts.carryforward_short > 0 or facts.carryforward_long > 0


def needs_8606(form: Form8606) -> bool:
    """Form 8606 instructions, "Who Must File": nondeductible contributions, a distribution from
    traditional IRAs with basis, or a conversion to a Roth IRA."""
    return form.line_1 > 0 or form.line_8 > 0 or (form.line_2 > 0 and form.line_7 > 0)


def files_a_return(facts: TaxUnitFacts, result: EngineResult, primary: bool) -> bool:
    """Whether the unit files. The household's first tax unit, the client, always does (SPEC: each
    featured household has a filled 1040). Another unit, such as an adult child, files when it owes tax,
    has tax withheld to claim back, or has a form to file (a Schedule D for a sale or a carryover, a
    Form 8606); one with a few hundred dollars of dividends and nothing else files nothing."""
    owes = result.summary.income_tax + result.summary.additional_medicare > 0
    return (
        primary
        or owes
        or facts.federal_withholding > 0
        or needs_schedule_d(facts)
        or any(needs_8606(form) for form in result.form_8606)
    )


def triggers(facts: TaxUnitFacts, result: EngineResult, primary: bool) -> dict[str, bool]:
    """Each form against the unit's facts: whether its return includes it. The book holds nothing that
    goes on Schedule 1 (no business, rental or other income, no adjustments), Schedule 3 (no credits,
    no estimated payments) or Schedule A (no household itemizes). A unit that files no return has none."""
    if not files_a_return(facts, result, primary):
        return dict.fromkeys(FORM_ORDER, False)
    return {
        "f1040": True,
        "f1040s1": False,
        "f1040s1a": result.deductions.senior > 0,
        "f1040s2": result.form_6251.line_11 > 0 or result.form_8960.line_17 > 0 or result.form_8959.line_7 > 0,
        "f1040s3": False,
        "f1040sa": result.deductions.itemized,
        "f1040sb": needs_schedule_b(facts),
        "f1040sd": needs_schedule_d(facts),
        "f8949": bool(facts.sales),
        "f8606": any(needs_8606(form) for form in result.form_8606),
        "f8960": result.form_8960.line_17 > 0,
        "f8959": result.form_8959.line_7 > 0,
    }


@dataclass(frozen=True)
class Box:
    """A Form 8949 box: which part and checkbox, and the Schedule D line its totals go to."""

    letter: str
    part: int
    schedule_d_line: str


BOXES = (Box("A", 1, "1b"), Box("B", 1, "2"), Box("D", 2, "8b"), Box("E", 2, "9"))


def _box(sale: Sale) -> Box:
    """Box A or D when the 1099-B reported the basis to the IRS (a covered lot), else B or E; the
    book's 1099-Bs report every sale."""
    return BOXES[(2 if sale.long_term else 0) + (0 if sale.covered else 1)]


@dataclass(frozen=True)
class Row:
    """A Form 8949 row: columns (d) to (h), with (e) the basis as the 1099-B reported it and (g) the
    adjustment that brings (h) to the true gain."""

    sale: Sale
    proceeds: Decimal
    basis: Decimal
    code: str
    adjustment: Decimal

    @property
    def gain(self) -> Decimal:
        return self.proceeds - self.basis + self.adjustment


def row(sale: Sale) -> Row:
    """Form 8949 instructions, columns (e) to (g): a covered lot keeps the 1099-B's basis in (e) and, when
    that basis is wrong, takes code B and the correction in (g); a disallowed wash-sale loss is code W,
    added back in (g). A noncovered lot enters its true basis."""
    basis = sale.reported_basis if sale.covered else sale.basis
    codes = ""
    adjustment = ZERO
    if basis != sale.basis:
        codes += "B"
        adjustment += basis - sale.basis
    if sale.disallowed:
        codes += "W"
        adjustment += sale.disallowed
    return Row(sale, sale.proceeds, basis, codes, adjustment)


def _chunks(rows: Sequence[Row]) -> Iterator[Sequence[Row]]:
    for start in range(0, len(rows), ROWS_A_PAGE):
        yield rows[start : start + ROWS_A_PAGE]


def _totals(rows: Sequence[Row]) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    return (
        sum((r.proceeds for r in rows), ZERO),
        sum((r.basis for r in rows), ZERO),
        sum((r.adjustment for r in rows), ZERO),
        sum((r.gain for r in rows), ZERO),
    )


def _header(values: dict[str, Value], household: Household, people: Sequence[str]) -> None:
    names = [household.person(p) for p in people]
    values["names"] = " & ".join(p.name for p in names)
    values["ssn"] = names[0].tax_id


def form_8949s(household: Household, facts: TaxUnitFacts) -> list[FilledForm]:
    """One Form 8949 a box a page of eleven rows, in the order the lots were sold."""
    filled: list[FilledForm] = []
    rows = [row(s) for s in facts.sales]
    for box in BOXES:
        in_box = [r for r in rows if _box(r.sale) == box]
        for page, chunk in enumerate(_chunks(in_box), start=1):
            values: dict[str, Value] = {}
            _header(values, household, [f.person_id for f in facts.filers])
            part = f"part{box.part}"
            if box.part == 2:
                values["names_page2"], values["ssn_page2"] = values["names"], values["ssn"]
            values[f"{part}_box_{box.letter.lower()}"] = True
            for n, r in enumerate(chunk, start=1):
                cell = f"{part}_row{n}"
                values[f"{cell}_a"] = f"{r.sale.units:,} sh {r.sale.security}"
                values[f"{cell}_b"] = r.sale.acquired.strftime("%m/%d/%Y")
                values[f"{cell}_c"] = r.sale.sold.strftime("%m/%d/%Y")
                values[f"{cell}_d"] = amount(r.proceeds)
                values[f"{cell}_e"] = amount(r.basis)
                if r.code:
                    values[f"{cell}_f"] = r.code
                    values[f"{cell}_g"] = amount(r.adjustment)
                values[f"{cell}_h"] = amount(r.gain)
            proceeds, basis, adjustment, gain = _totals(chunk)
            values[f"{part}_total_d"] = amount(proceeds)
            values[f"{part}_total_e"] = amount(basis)
            if adjustment:
                values[f"{part}_total_g"] = amount(adjustment)
            values[f"{part}_total_h"] = amount(gain)
            filled.append(FilledForm("f8949", f"f8949-{box.letter}-{page}.pdf", values))
    return filled


def schedule_d(household: Household, facts: TaxUnitFacts, result: EngineResult) -> FilledForm:
    d = result.schedule_d
    values: dict[str, Value] = {}
    _header(values, household, [f.person_id for f in facts.filers])
    values["qof_no"] = True  # no qualified opportunity fund in the book
    rows = [row(s) for s in facts.sales]
    for box in BOXES:
        in_box = [r for r in rows if _box(r.sale) == box]
        if in_box:
            proceeds, basis, adjustment, gain = _totals(in_box)
            line = box.schedule_d_line
            values[f"{line}_d"] = amount(proceeds)
            values[f"{line}_e"] = amount(basis)
            if adjustment:
                values[f"{line}_g"] = amount(adjustment)
            values[f"{line}_h"] = amount(gain)
    # Lines 6, 14 and 21 are losses the form itself prints in parentheses: the amount goes in plain.
    if d.short_term_carryover:
        values["6"] = amount(d.short_term_carryover)
    values["7"] = amount(d.net_short_term)
    if d.long_term_carryover:
        values["14"] = amount(d.long_term_carryover)
    values["15"] = amount(d.net_long_term)
    values["16"] = amount(d.net_gain)
    # Part III's flow: a gain on line 16 asks line 17; "both gains" goes on to line 20 and stops there,
    # anything else (a gain on 16 but not on 15, a loss through line 21, or zero) ends at line 22.
    both = d.net_gain > 0 and d.net_long_term > 0
    if d.net_gain > 0:
        values["17_yes" if both else "17_no"] = True
    if both:
        # No collectibles and no real property in the book: lines 18 and 19 are zero, so line 20 is "Yes".
        values["20_yes"] = True
    else:
        if d.net_gain < 0:
            values["21"] = amount(d.loss_allowed)
        values["22_yes" if facts.qualified_dividends > 0 else "22_no"] = True
    return FilledForm("f1040sd", "f1040sd.pdf", values)


def schedule_b(household: Household, facts: TaxUnitFacts) -> FilledForm:
    values: dict[str, Value] = {}
    _header(values, household, [f.person_id for f in facts.filers])
    payers = [p for p in facts.payers if p.ordinary_dividends > 0]
    for n, payer in enumerate(payers, start=1):
        values[f"part2_row{n}_payer"] = f"Custodian, account {payer.account_id}"
        values[f"part2_row{n}_amount"] = amount(payer.ordinary_dividends)
    values["6"] = amount(facts.ordinary_dividends)
    # Part III: the book's households hold no foreign account and no foreign trust.
    values["7a_no"] = True
    values["8_no"] = True
    return FilledForm("f1040sb", "f1040sb.pdf", values)


def form_8606(household: Household, form: Form8606) -> FilledForm:
    person = household.person(form.person_id)
    values: dict[str, Value] = {"names": person.name, "ssn": person.tax_id}
    # "Did you take a distribution ... or make a Roth IRA conversion?" No: line 3 goes to line 14 and the
    # rest of Part I is left blank.
    moved = form.line_7 + form.line_8 > 0
    lines = {"1": form.line_1, "2": form.line_2, "3": form.line_3, "14": form.line_14}
    if moved:
        lines |= {
            "5": form.line_5,
            "6": form.line_6,
            "7": form.line_7,
            "8": form.line_8,
            "9": form.line_9,
            "11": form.line_11,
            "12": form.line_12,
            "13": form.line_13,
        }
        whole, _, places = f"{form.line_10:.3f}".partition(".")
        values["10_before_decimal"], values["10_after_decimal"] = whole, places
    if form.line_7 > 0:
        lines |= {"15a": form.line_15a, "15c": form.line_15c}
    if form.line_8 > 0:
        lines |= {"16": form.line_16, "17": form.line_17, "18": form.line_18}
    for line, value in lines.items():
        values[line] = amount(value)
    return FilledForm("f8606", f"f8606-{form.person_id}.pdf", values)


def schedule_1a(household: Household, facts: TaxUnitFacts, result: EngineResult, rules: Rules) -> FilledForm:
    """Part I (modified AGI) and Part V (the enhanced deduction for seniors)."""
    values: dict[str, Value] = {}
    _header(values, household, [f.person_id for f in facts.filers])
    joint = facts.filing_status == "married_filing_jointly"
    magi = result.form_1040.agi
    threshold = rules.value("senior_deduction_phaseout_joint" if joint else "senior_deduction_phaseout_single")
    excess = max(ZERO, magi - threshold)
    reduction = cents(rules.value("senior_deduction_phaseout_rate") * excess)
    each = max(ZERO, rules.value("senior_deduction") - reduction)
    values["1"] = amount(magi)
    values["3"] = amount(magi)
    values["31"] = amount(magi)
    values["32"] = amount(threshold)
    if excess:
        values["33"] = amount(excess)
        values["34"] = amount(reduction)
    values["35"] = amount(each)
    seniors = [f for f in facts.filers if f.age >= SENIOR_AGE]
    if facts.filers[0].age >= SENIOR_AGE:
        values["36a"] = amount(each)
    if joint and len(facts.filers) > 1 and facts.filers[1].age >= SENIOR_AGE:
        values["36b"] = amount(each)
    values["37"] = amount(each * len(seniors))
    values["38"] = amount(result.deductions.senior)
    return FilledForm("f1040s1a", "f1040s1a.pdf", values)


def schedule_2(household: Household, facts: TaxUnitFacts, result: EngineResult) -> FilledForm:
    values: dict[str, Value] = {}
    _header(values, household, [f.person_id for f in facts.filers])
    amt = result.form_6251.line_11
    _on_return(values, l_2=amt, l_3=amt, l_11=result.form_8959.line_7, l_12=result.form_8960.line_17)
    values["21"] = amount(result.form_8959.line_7 + result.form_8960.line_17)
    return FilledForm("f1040s2", "f1040s2.pdf", values)


def form_8960(household: Household, facts: TaxUnitFacts, result: EngineResult) -> FilledForm:
    f = result.form_8960
    values: dict[str, Value] = {}
    _header(values, household, [x.person_id for x in facts.filers])
    _on_return(values, l_1=f.line_1, l_2=f.line_2, l_5a=f.line_5a)
    if f.line_5a:
        values["5d"] = amount(f.line_5a)
    for line, value in (("8", f.line_8), ("12", f.line_12), ("13", f.line_13), ("14", f.line_14)):
        values[line] = amount(value)
    values["15"] = amount(max(ZERO, f.line_13 - f.line_14))
    values["16"] = amount(f.line_16)
    values["17"] = amount(f.line_17)
    return FilledForm("f8960", "f8960.pdf", values)


def form_8959(household: Household, facts: TaxUnitFacts, result: EngineResult) -> FilledForm:
    f = result.form_8959
    values: dict[str, Value] = {}
    _header(values, household, [x.person_id for x in facts.filers])
    values["1"] = amount(f.line_1)
    values["4"] = amount(f.line_1)
    values["5"] = amount(f.line_5)
    values["6"] = amount(f.line_6)
    values["7"] = amount(f.line_7)
    values["18"] = amount(f.line_7)
    return FilledForm("f8959", "f8959.pdf", values)


def form_1040(household: Household, facts: TaxUnitFacts, result: EngineResult) -> FilledForm:
    f = result.form_1040
    values: dict[str, Value] = {}
    people = [household.person(x.person_id) for x in facts.filers]
    # The 1040's SSN boxes take the nine digits alone.
    values["name"], values["last_name"] = _names(people[0])
    values["ssn"] = people[0].tax_id.replace("-", "")
    if facts.filing_status == "married_filing_jointly" and len(people) > 1:
        values["spouse_name"], values["spouse_last_name"] = _names(people[1])
        values["spouse_ssn"] = people[1].tax_id.replace("-", "")
    values[STATUS_KEY[facts.filing_status]] = True
    values["digital_assets_no"] = True  # the book holds no digital asset
    for n, filer in enumerate(facts.filers):
        person = household.person(filer.person_id)
        if person.died is not None and person.died.year == TAX_YEAR:
            # A joint return for a spouse who died in the year: the "Deceased" box and the date of death.
            prefix = "deceased" if n == 0 else "spouse_deceased"
            values["deceased"] = True
            values[f"{prefix}_mm"] = f"{person.died.month:02d}"
            values[f"{prefix}_dd"] = f"{person.died.day:02d}"
            values[f"{prefix}_yyyy"] = str(person.died.year)
        # Line 12d, "born before January 2, 1961": 65 by the end of 2025, or at death (Pub. 501).
        if age_for_the_year(person.born, person.died) >= SENIOR_AGE:
            values["12d_you_born_before_1961" if n == 0 else "12d_spouse_born_before_1961"] = True
    ira_gross = f.ira_distributions
    _on_return(
        values,
        l_1a=f.wages,
        l_1z=f.wages,
        l_2a=f.tax_exempt_interest,
        l_2b=f.taxable_interest,
        l_3a=f.qualified_dividends,
        l_3b=f.ordinary_dividends,
        l_4a=ira_gross,
        l_5a=f.pensions,
        l_5b=f.taxable_pensions,
        l_6a=f.social_security,
        l_13b=f.senior_deduction,
        l_17=f.amt,
        l_23=f.niit + f.additional_medicare,
    )
    if ira_gross:
        values["4b"] = amount(f.taxable_ira)
        if any(i.qcd for i in facts.iras):
            values["4c_2"] = True  # QCD
    if f.social_security:
        values["6b"] = amount(f.taxable_social_security)
    if facts.sales or facts.carryforward_short or facts.carryforward_long:
        values["7a"] = amount(f.capital_gain)
    for line, value in (
        ("9", f.total_income),
        ("11a", f.agi),
        ("11b", f.agi),
        ("12e", f.deduction),
        ("14", f.deduction + f.senior_deduction),
        ("15", f.taxable_income),
        ("16", f.tax),
        ("18", f.tax + f.amt),
        ("22", f.tax + f.amt),
        ("24", f.total_tax),
    ):
        values[line] = amount(value)
    if f.withholding:
        values["25b"] = amount(f.withholding)
        values["25d"] = amount(f.withholding)
        values["33"] = amount(f.withholding)
    if f.withholding > f.total_tax:
        values["34"] = amount(f.withholding - f.total_tax)
        values["35a"] = amount(f.withholding - f.total_tax)
    else:
        values["37"] = amount(f.total_tax - f.withholding)
    return FilledForm("f1040", "f1040.pdf", values)


def return_forms(household: Household, facts: TaxUnitFacts, result: EngineResult) -> list[FilledForm]:
    """Every PDF of the unit's 2025 return, the 1040 first, then each triggered schedule and form; none
    for a unit that files no return."""
    primary = facts.tax_unit_id == household.tax_units[0].tax_unit_id
    triggered = triggers(facts, result, primary)
    if not triggered["f1040"]:
        return []
    rules = load_rules(TAX_YEAR)
    forms = [form_1040(household, facts, result)]
    if triggered["f1040s1a"]:
        forms.append(schedule_1a(household, facts, result, rules))
    if triggered["f1040s2"]:
        forms.append(schedule_2(household, facts, result))
    if triggered["f1040sb"]:
        forms.append(schedule_b(household, facts))
    if triggered["f1040sd"]:
        forms.append(schedule_d(household, facts, result))
    if triggered["f8949"]:
        forms += form_8949s(household, facts)
    forms += [form_8606(household, form) for form in result.form_8606 if needs_8606(form)]
    if triggered["f8960"]:
        forms.append(form_8960(household, facts, result))
    if triggered["f8959"]:
        forms.append(form_8959(household, facts, result))
    return forms
