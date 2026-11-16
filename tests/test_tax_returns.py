"""docs/PLAN.md, slice 8: which schedules and forms each featured household's return includes, and what
goes on Form 8949. Each expected trigger is worked from the unit's facts, never read from the code."""

import dataclasses
from decimal import Decimal
from pathlib import Path

import pytest

from casebook.generate.background import generate_background
from casebook.generate.script import load_scripts
from casebook.model.events import parse_event
from casebook.model.files import event_log_path, read_json
from casebook.model.household import Household
from casebook.model.tax import TAX_YEAR, TaxUnitFacts, parse_facts
from casebook.replay import replay
from casebook.securities.market import build_market
from casebook.securities.master import load_master
from casebook.sources.context import SNAPSHOT_DAYS
from casebook.tax.engine import compute
from casebook.tax.forms.returns import (
    BOXES,
    amount,
    form_1040,
    form_8606,
    form_8949s,
    return_forms,
    row,
    schedule_d,
    triggers,
)

from .conftest import SCRIPTS, SEED, built

D = Decimal
TAXABLE = ("joint_taxable", "individual_taxable")

# Each public featured unit's forms, from its facts. Thresholds: Schedule B over $1,500 of ordinary
# dividends; Form 8959 over $250,000 of joint Medicare wages; Form 8960 with net investment income and
# modified AGI over $250,000 (joint) or $200,000; Schedule 1-A for a filer 65 or older; Form 8606 for a
# nondeductible contribution or a conversion; Schedule D and Form 8949 for a sale; Schedule 2 with 8959
# or 8960. A household's first unit always files; another files when it owes tax, has withholding to claim
# or has a form to file.
EXPECTED = {
    # Wages 212,000 + 186,000 = 398,000; dividends 1,584.97; AGI 406,332.97; a 7,000 backdoor conversion.
    "TU-1204-1": {"f1040", "f1040s2", "f1040sb", "f8606", "f8959", "f8960"},
    # Wages 377,000; dividends 1,444.51, under 1,500; AGI 378,444.51; a 7,000 backdoor conversion.
    "TU-1587-1": {"f1040", "f1040s2", "f8606", "f8959", "f8960"},
    # Wages 228,500, under 250,000; AGI 316,922.39 with 88,422.39 of investment income; one sale.
    "TU-2316-1": {"f1040", "f1040s2", "f1040sb", "f1040sd", "f8949", "f8960"},
    # AGI 238,610.68, under 250,000; dividends 13,407.79; one sale.
    "TU-2749-1": {"f1040", "f1040sb", "f1040sd", "f8949"},
    # Wages 1,313,944; AGI 1,411,617.78; two lots sold.
    "TU-3058-1": {"f1040", "f1040s2", "f1040sb", "f1040sd", "f8949", "f8959", "f8960"},
    # Wages 1,132,860; AGI 1,175,989.70; three lots sold.
    "TU-3462-1": {"f1040", "f1040s2", "f1040sb", "f1040sd", "f8949", "f8959", "f8960"},
    # Single, 67; a 60,000 conversion with 38,500 of basis; dividends 4,638.03.
    "TU-4105-1": {"f1040", "f1040s1a", "f1040sb", "f8606"},
    # Single, 67; a 60,000 conversion, no basis on file (the unresolved twin); dividends 4,589.50.
    "TU-4633-1": {"f1040", "f1040s1a", "f1040sb", "f8606"},
    # Under 65; an 8,000 nondeductible contribution; dividends 6,840.49; one sale; no tax owed.
    "TU-4821-1": {"f1040", "f1040sb", "f1040sd", "f8606", "f8949"},
    # Single, 29: 731.45 of dividends, no tax, no withholding, nothing to file.
    "TU-4821-2": set(),
    # 73 and 70; dividends 1,692.05.
    "TU-5271-1": {"f1040", "f1040s1a", "f1040sb"},
    # 73 and 68; dividends 1,568.73.
    "TU-5814-1": {"f1040", "f1040s1a", "f1040sb"},
    # 78 and 76; dividends 1,401.01; 965.97 withheld from the RMD.
    "TU-6047-1": {"f1040", "f1040s1a"},
    # Single, 78; dividends 1,256.81; 988.25 withheld.
    "TU-6590-1": {"f1040", "f1040s1a"},
    # Single, 46, no income.
    "TU-6590-2": set(),
    # Under 65; an 8,000 nondeductible contribution; dividends 6,253.97; one sale.
    "TU-7350-1": {"f1040", "f1040sb", "f1040sd", "f8606", "f8949"},
    # Single, 30: 687.33 of dividends, nothing to file.
    "TU-7350-2": set(),
    # Dividends 4,713.67; one sale at a loss (the wash sale), carried to 2026.
    "TU-9234-1": {"f1040", "f1040sb", "f1040sd", "f8949"},
    # Dividends 4,413.49; one sale.
    "TU-9571-1": {"f1040", "f1040sb", "f1040sd", "f8949"},
}


def featured_units(book: Path) -> list[TaxUnitFacts]:
    return [
        parse_facts(raw) for household in built(book) for raw in read_json(book, event_log_path(household))["tax_units"]
    ]


def test_each_featured_unit_s_return_includes_the_forms_its_facts_trigger(book: Path) -> None:
    units = featured_units(book)
    assert {u.tax_unit_id for u in units} == set(EXPECTED)
    for unit in units:
        primary = unit.tax_unit_id.endswith("-1")
        found = {form for form, on in triggers(unit, compute(unit), primary).items() if on}
        assert found == EXPECTED[unit.tax_unit_id], unit.tax_unit_id
        # Schedules 1 and 3 and Schedule A: nothing in the book goes on them.
        assert not found & {"f1040s1", "f1040s3", "f1040sa"}


def test_every_featured_household_files_a_1040(book: Path) -> None:
    for household in built(book):
        units = [u for u in featured_units(book) if u.household_id == household]
        assert any(EXPECTED[u.tax_unit_id] for u in units), household


def unit_of(book: Path, unit_id: str) -> TaxUnitFacts:
    (unit,) = [u for u in featured_units(book) if u.tax_unit_id == unit_id]
    return unit


def test_the_custodian_s_zero_basis_takes_code_b_on_form_8949(book: Path) -> None:
    """HH-3058: the 1099-B reports $0 for both released lots; their true bases are 172,848.00 and
    183,920.00. Column (e) keeps the reported $0, (f) is B, (g) corrects it, and (h) is the true gain:
    218,888.00 - 0 - 172,848.00 = 46,040.00 and 218,888.00 - 0 - 183,920.00 = 34,968.00."""
    unit = unit_of(book, "TU-3058-1")
    rows = [row(s) for s in unit.sales]
    assert [(r.basis, r.code, r.adjustment, r.gain) for r in rows] == [
        (D("0.00"), "B", D("-172848.00"), D("46040.00")),
        (D("0.00"), "B", D("-183920.00"), D("34968.00")),
    ]


def test_a_wash_sale_takes_code_w_on_form_8949(book: Path) -> None:
    """HH-9234: 847 shares, proceeds 224,556.64, basis 278,072.81 (reported correctly); 31,591.60 of the
    loss disallowed: (h) = 224,556.64 - 278,072.81 + 31,591.60 = -21,924.57."""
    (r,) = [row(s) for s in unit_of(book, "TU-9234-1").sales]
    assert (r.basis, r.code, r.adjustment, r.gain) == (D("278072.81"), "W", D("31591.60"), D("-21924.57"))


def test_form_8949_totals_equal_the_closed_lot_replay(book: Path) -> None:
    """For every featured unit, Form 8949's columns (d) and (h), summed across its copies, equal the
    proceeds and the gains of the lots the sealed event log's replay closed in 2025 in the unit's
    taxable accounts, with the disallowed wash-sale losses added back to the gains."""
    for household in built(book):
        log = read_json(book, event_log_path(household))
        events = tuple(parse_event(e) for e in log["events"])
        closed = [c for c in replay(events, SNAPSHOT_DAYS).closed if c.sold.year == TAX_YEAR]
        for raw in log["tax_units"]:
            unit = parse_facts(raw)
            accounts = {s.account_id for s in unit.sales}
            lots = [c for c in closed if c.account_id in accounts]
            filed = form_8949s(read_household(book, household), unit)
            proceeds = sum(
                (parse_amount(str(v)) for f in filed for k, v in f.values.items() if k.endswith("_total_d")),
                D(0),
            )
            assert proceeds == sum((c.proceeds for c in lots), D(0)), unit.tax_unit_id
            disallowed = sum((s.disallowed for s in unit.sales), D(0))
            gain = sum(
                (parse_amount(str(v)) for f in filed for k, v in f.values.items() if k.endswith("_total_h")), D(0)
            )
            assert gain == sum((c.proceeds - c.cost for c in lots), D(0)) + disallowed, unit.tax_unit_id


def parse_amount(text: str) -> Decimal:
    negative = text.startswith("(")
    value = D(text.strip("()").replace(",", ""))
    return -value if negative else value


def read_household(book: Path, household: str) -> Household:
    del book
    (script,) = [s for s in load_scripts(SCRIPTS) if s.household.household_id == household]
    return script.household


@pytest.mark.parametrize(
    ("value", "shown"),
    [(D("1234.5"), "1,234.50"), (D("-3000"), "(3,000.00)"), (D("0"), "0.00"), (D("1000000"), "1,000,000.00")],
)
def test_amounts_are_shown_to_the_cent_with_losses_in_parentheses(value: Decimal, shown: str) -> None:
    assert amount(value) == shown


def test_a_box_s_eleven_rows_fill_a_page_and_the_twelfth_starts_another(book: Path) -> None:
    unit = unit_of(book, "TU-9234-1")
    (sale,) = unit.sales
    twelve = dataclasses.replace(unit, sales=(sale,) * 12)
    filed = form_8949s(read_household(book, "HH-9234"), twelve)
    assert [f.file for f in filed] == ["f8949-D-1.pdf", "f8949-D-2.pdf"]
    assert "part2_row11_a" in filed[0].values and "part2_row1_a" in filed[1].values
    assert "part2_row2_a" not in filed[1].values
    assert {b.letter for b in BOXES} == {"A", "B", "D", "E"}


def test_a_unit_with_nothing_to_file_has_no_return(book: Path) -> None:
    unit = unit_of(book, "TU-4821-2")
    assert return_forms(read_household(book, "HH-4821"), unit, compute(unit)) == []


def test_a_spouse_who_died_in_the_year_is_marked_deceased_on_the_1040(full_book: Path) -> None:
    """Archetype 8's drawn households file jointly for the year a spouse died: the 1040's "Deceased" box,
    with that spouse's date of death."""
    market = build_market(load_master(), SEED)
    checked = 0
    for script in generate_background(SEED, market, frozenset({8})):
        household = script.household
        for raw in read_json(full_book, event_log_path(household.household_id))["tax_units"]:
            unit = parse_facts(raw)
            dead = [
                (n, household.person(f.person_id).died)
                for n, f in enumerate(unit.filers)
                if household.person(f.person_id).died is not None
            ]
            if not dead or unit.filing_status != "married_filing_jointly":
                continue
            ((n, died),) = dead
            assert died is not None and died.year == TAX_YEAR
            values = form_1040(household, unit, compute(unit)).values
            prefix = "deceased" if n == 0 else "spouse_deceased"
            assert values["deceased"] is True
            assert (values[f"{prefix}_mm"], values[f"{prefix}_dd"], values[f"{prefix}_yyyy"]) == (
                f"{died.month:02d}",
                f"{died.day:02d}",
                "2025",
            )
            checked += 1
    assert checked == 8


def test_the_client_unit_files_even_with_no_tax_and_no_form_but_another_unit_does_not(book: Path) -> None:
    """HH-6047's couple files because 965.97 was withheld; without it they owe nothing and have no form,
    and still file, as the household's first unit. HH-4821's second unit, with 731.45 of dividends, does not."""
    couple = dataclasses.replace(unit_of(book, "TU-6047-1"), federal_withholding=D(0))
    assert compute(couple).summary.income_tax == 0
    assert triggers(couple, compute(couple), primary=True)["f1040"]
    filed = return_forms(read_household(book, "HH-6047"), couple, compute(couple))
    assert filed[0].file == "f1040.pdf"
    second = unit_of(book, "TU-4821-2")
    assert not any(triggers(second, compute(second), primary=False).values())


def test_schedule_d_answers_line_22_when_line_17_is_no(book: Path) -> None:
    """Reviewers A and B, slice 8 round 1. HH-3058: a short-term gain of 81,008.00 and no long-term gain, so
    line 17 is "No" ("skip lines 18 through 21, and go to line 22"), and with 15,462.53 of qualified
    dividends line 22 is "Yes"."""
    unit = unit_of(book, "TU-3058-1")
    values = schedule_d(read_household(book, "HH-3058"), unit, compute(unit)).values
    assert (values["15"], values["16"]) == ("0.00", "81,008.00")
    assert values["17_no"] is True and values["22_yes"] is True
    assert "17_yes" not in values and "20_yes" not in values and "21" not in values


def test_schedule_d_prints_its_losses_inside_the_form_s_own_parentheses(book: Path) -> None:
    """Reviewer B, slice 8 round 1: lines 6, 14 and 21 are printed "( )" on the form. HH-9234's loss of
    21,924.57 is limited to 3,000.00 on line 21; with a long-term carryover of 5,000.00 in, line 14 holds
    5,000.00 and line 15 is 21,924.57 + 5,000.00 = (26,924.57)."""
    unit = dataclasses.replace(unit_of(book, "TU-9234-1"), carryforward_long=D("5000.00"))
    values = schedule_d(read_household(book, "HH-9234"), unit, compute(unit)).values
    assert (values["14"], values["15"], values["16"], values["21"]) == (
        "5,000.00",
        "(26,924.57)",
        "(26,924.57)",
        "3,000.00",
    )
    assert values["22_yes"] is True and "17_no" not in values


def test_form_8606_stops_at_line_3_without_a_distribution_or_conversion(book: Path) -> None:
    """Reviewer A, slice 8 round 1. HH-4821: an 8,000.00 nondeductible contribution, no distribution and no
    conversion: line 3 goes to line 14 and lines 4 to 13 stay blank."""
    unit = unit_of(book, "TU-4821-1")
    (form,) = [f for f in compute(unit).form_8606 if f.line_1 > 0]
    values = form_8606(read_household(book, "HH-4821"), form).values
    assert {k for k in values if k[0].isdigit()} == {"1", "2", "3", "14"}
    assert (values["1"], values["3"], values["14"]) == ("8,000.00", "8,000.00", "8,000.00")
