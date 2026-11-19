"""The fabricated-figure rule's derivations (the owner, 18 November 2026: option 1 of
`docs/decisions/2026-11-18-fabricated-figure-false-zeros.md`, with (b) over the cited household's files and (f)
rounding). Each accepted case is an answer from the full pass (`pass-20261118T080940Z-4471`) that the strict rule
zeroed, on a small copy of the files it read; each refused one is an invented figure the rule must still zero."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from casebook.graders.common import Figure, Support, figures
from casebook.graders.derivations import expressions, rounding_unit

POSITIONS = (
    "account_id,security_id,security,units,price,price_label,market_value,valuation_date,known_as_of\n"
    "SYN-27490001,SEC-0002,VXUS,416,203.92,synthetic,84830.72,2026-04-15,2026-04-15\n"
    "SYN-27490002,SEC-0011,LQD,2380,108.64,synthetic,258560.16,2026-04-15,2026-04-15\n"
    "SYN-27490002,SEC-0003,IVV,40,680.00,synthetic,27200.00,2026-04-15,2026-04-15\n"
    "SYN-27490003,SEC-0003,IVV,100,680.00,synthetic,68000.00,2026-04-15,2026-04-15\n"
    "SYN-27490003,SEC-0003,IVV,100,670.00,synthetic,67000.00,2025-12-31,2025-12-31\n"
)
CASH = (
    "account_id,settled_cash,unsettled_cash,valuation_date,known_as_of\n"
    "SYN-27490001,32000.00,0.00,2026-04-15,2026-04-15\n"
    "SYN-27490002,1463.16,0.00,2026-04-15,2026-04-15\n"
    "SYN-27490003,1055.23,0.00,2026-04-15,2026-04-15\n"
)
TAX_LOTS = (
    "account_id,lot_id,security_id,security,acquired_date,units,cost_basis,valuation_date,known_as_of\n"
    "SYN-27490002,L-27490002-01,SEC-0011,LQD,2016-03-02,2380,257498.60,2026-04-15,2026-04-15\n"
)
TRANSACTIONS = (
    "account_id,transaction_id,date,type,amount\n"
    "SYN-27490002,T-2749-0040,2025-06-02,conversion,-7000.00\n"
    "SYN-27490002,T-2749-0041,2025-12-31,balance,228659.62\n"
)
HOUSEHOLD = {
    "household_id": "HH-2749",
    "people": [
        {"person_id": "P-2749-1", "name": "Bernard Lachance", "birth_date": "1947-05-09"},
        {"person_id": "P-2749-2", "name": "Celestine Abara", "birth_date": "1952-02-17"},
    ],
}


def _household(root: Path) -> Path:
    (root / "custodian").mkdir(parents=True)
    (root / "portfolio").mkdir()
    (root / "custodian" / "positions.csv").write_text(POSITIONS, encoding="utf-8")
    (root / "custodian" / "cash.csv").write_text(CASH, encoding="utf-8")
    (root / "custodian" / "tax_lots.csv").write_text(TAX_LOTS, encoding="utf-8")
    (root / "custodian" / "transactions.csv").write_text(TRANSACTIONS, encoding="utf-8")
    (root / "portfolio" / "household.json").write_text(json.dumps(HOUSEHOLD), encoding="utf-8")
    return root


@pytest.fixture
def fixtures(tmp_path: Path) -> Path:
    return _household(tmp_path / "workspace")


@pytest.fixture
def book(tmp_path: Path) -> Path:
    """A whole-book workspace: three households' folders."""
    root = tmp_path / "book"
    for household in ("HH-0120", "HH-0218", "HH-2749"):
        _household(root / "households" / household)
    return root


def _figure(label: str, value: str | int, source: str) -> Figure:
    """A cited figure as a grader reads it from an answer's json block."""
    problems: list[str] = []
    (figure,) = figures([{"label": label, "value": value, "source": source}], problems)
    assert not problems
    return figure


def _judged(fixtures: Path, *figures: Figure, prose: str = "", key: tuple[str, ...] = ()) -> str | None:
    support = Support(fixtures, [Decimal(k) for k in key])
    return support.first_fabrication(prose, figures, ())


# (a) the arithmetic the answer shows


@pytest.mark.parametrize(
    "label",
    [
        "LQD unrealized long-term gain (258,560.16 - 257,498.60)",  # T-MTG-04 skill, repeats 1 and 2
        "LQD unrealized loss: 257,498.60 - 258,560.16",
        "LQD gain, 2026-04-15 = 258,560.16 less 257,498.60",
    ],
)
def test_arithmetic_shown_over_figures_in_the_files_is_accepted(fixtures: Path, label: str) -> None:
    assert _judged(fixtures, _figure(label, "1061.56", "custodian/tax_lots.csv")) is None


def test_a_conversion_s_taxable_part_shown_as_a_formula_is_accepted(fixtures: Path) -> None:
    # T-MTG-06 skill, repeat 1: "HH-0218 taxable part of conversion (7000 - 7000*7000/228659.62) = 6785.71".
    label = "HH-0218 taxable part of conversion (7000 - 7000*7000/228659.62)"
    assert _judged(fixtures, _figure(label, "6785.71", "custodian/positions.csv")) is None
    other = "HH-0690 taxable part of conversion = 7000 x (1 - 7000/228659.62)"  # T-MTG-06 skill, repeat 2
    assert _judged(fixtures, _figure(other, "6785.71", "custodian/positions.csv")) is None


def test_a_percentage_shown_as_a_ratio_is_accepted(fixtures: Path) -> None:
    # T-CMP-01 skill, repeat 1: "(825134.04 / 3895524.87), percent = 21.18".
    label = "LQD as share of the account (258,560.16 / 287,223.32), percent"
    assert _judged(fixtures, _figure(label, "90.02", "custodian/positions.csv")) is None


def test_arithmetic_may_stand_on_another_figure_the_answer_derived(fixtures: Path) -> None:
    # T-MTG-04 skill, repeat 1: "Combined IRA value (380,605.02 + 207,075.11) = 587680.13".
    first = _figure("SYN-27490002 value incl. cash (258,560.16 + 27,200.00 + 1,463.16)", "287223.32", "custodian")
    combined = _figure("Combined (287,223.32 + 69,055.23)", "356278.55", "custodian/positions.csv")
    second = _figure("SYN-27490003 value incl. cash (68,000.00 + 1,055.23)", "69055.23", "custodian")
    assert _judged(fixtures, combined, first, second) is None


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("LQD unrealized gain (258,560.16 - 257,498.60)", "1161.56"),  # wrong arithmetic
        ("LQD unrealized gain (258,560.16 - 257,400.00)", "1160.16"),  # an operand in no file
        ("LQD unrealized gain (258,560.16 - 257,498.60) + 412.07", "1473.63"),
    ],
)
def test_arithmetic_that_is_wrong_or_stands_on_an_invented_number_is_fabricated(
    fixtures: Path, label: str, value: str
) -> None:
    assert _judged(fixtures, _figure(label, value, "custodian/tax_lots.csv")) is not None


def test_identifiers_and_dates_are_not_read_as_arithmetic() -> None:
    # T-CMP-04 skill, repeat 1: an account number and a date sit beside the roll-forward.
    text = "SYN-46330002 cash roll-forward to 2025-12-31: 5,978.12 + 57,984.75 - 60,000.00 - 1,072.56 + 146.94 + 637.26"
    results = {e.result for e in expressions(text)}
    assert Decimal("3674.51") in results
    assert all(Decimal(46330002) not in e.operands and Decimal(2025) not in e.operands for e in expressions(text))


# (b) a sum or difference of values in the cited household's files


@pytest.mark.parametrize(
    ("label", "value", "source"),
    [
        # T-CMP-02 checklist, repeat 1: positions and cash on one date, two cited files.
        ("Household total value 2026-04-15", "473109.27", "custodian/positions.csv; custodian/cash.csv"),
        # T-CMP-04 checklist, repeat 1: the same, citing positions.csv alone (cash counted from cash.csv).
        ("Household value at 2026-04-15", "473109.27", "custodian/positions.csv"),
        # T-MTG-04 basic: a gain from positions less the lot's basis, citing the lots alone.
        ("LQD unrealized long-term gain", "1061.56", "custodian/tax_lots.csv"),
        # An account's positions on one date.
        ("SYN-27490002 positions at 2026-04-15", "285760.16", "custodian/positions.csv"),
    ],
)
def test_a_total_over_the_household_s_records_is_accepted(fixtures: Path, label: str, value: str, source: str) -> None:
    assert _judged(fixtures, _figure(label, value, source)) is None


@pytest.mark.parametrize("value", ["4944.13", "473190.27", "285761.16", "48113.27"])
def test_an_invented_amount_that_no_total_gives_is_fabricated(fixtures: Path, value: str) -> None:
    assert _judged(fixtures, _figure("Household total value", value, "custodian/positions.csv")) is not None
    assert _judged(fixtures, prose=f"The household held ${value} in all.") is not None


def test_a_price_is_still_read_never_derived(fixtures: Path) -> None:
    # A sum of the right size does not make good a price no file holds.
    assert _judged(fixtures, _figure("IVV price", "1350.00", "custodian/positions.csv")) is not None


# (c) an age from a birth date


@pytest.mark.parametrize(
    "label",
    ["Bernard's age at end of 2025", "Bernard's age at end of 2025 (2025 - 1947)", "Age attained in 2025"],
)
def test_an_age_from_a_birth_date_in_the_cited_file_is_accepted(fixtures: Path, label: str) -> None:
    # T-REC-03 and T-REC-04, every arm and repeat: "age 78" from a birth date in 1947.
    assert _judged(fixtures, _figure(label, 78, "portfolio/household.json")) is None


@pytest.mark.parametrize(("label", "value"), [("Bernard's age at end of 2025", 81), ("Years held", 78)])
def test_an_age_no_birth_date_gives_or_a_number_not_called_an_age_is_fabricated(
    fixtures: Path, label: str, value: int
) -> None:
    assert _judged(fixtures, _figure(label, value, "portfolio/household.json")) is not None


# (d) a count of what the cited path holds


@pytest.mark.parametrize(
    ("label", "value", "source"),
    [
        ("Households reviewed", 3, "households/"),  # T-REC-06 and T-CMP-06: "Households reviewed = 92"
        ("Households reviewed", 3, "households/*/portfolio/household.json"),
        ("Custodian position rows valued 2026-04-15, all households", 12, "households/*/custodian/positions.csv"),
        # T-REC-06 checklist, repeat 3: a placeholder for the household folder.
        ("Custodian position rows", 15, "households/<household ID>/custodian/positions.csv"),
        ("Position or cash mismatches found", 0, "households/*/custodian/cash.csv"),
    ],
)
def test_a_count_of_the_records_at_the_cited_path_is_accepted(book: Path, label: str, value: int, source: str) -> None:
    assert _judged(book, _figure(label, value, source)) is None


def test_a_count_larger_than_the_path_holds_is_fabricated(book: Path) -> None:
    assert _judged(book, _figure("Households reviewed", 92, "households/*/portfolio/household.json")) is not None
    assert _judged(book, _figure("Households reviewed", 3, "nowhere/")) is not None


# (e) a parameter of the rules table


def test_a_rules_table_parameter_in_prose_is_accepted(fixtures: Path) -> None:
    # T-TAX-03 and T-TAX-04: "$3,000", the capital-loss limit; T-MTG-03 and T-MTG-04: "$31,500", the 2025
    # standard deduction for a joint return.
    assert _judged(fixtures, prose="Only $3,000 of the net loss offsets ordinary income.") is None
    assert _judged(fixtures, prose="The standard deduction is $31,500.") is None
    assert _judged(fixtures, prose="Only $3,100 of the net loss offsets ordinary income.") is not None


# A value that is not a number


@pytest.mark.parametrize(
    "value",
    [
        "confirmed",  # T-MTG-03 basic, repeat 1
        "Elena Castellanos (spouse of joint owner Graham Reid, filing jointly)",  # T-TAX-04 basic, repeat 1
        "traditional_ira, Anika Nwachukwu (spouse)",  # T-TAX-06 skill, repeat 1
        "2023-01-05",  # a date: not a number
    ],
)
def test_a_value_that_is_not_a_number_is_never_fabricated(fixtures: Path, value: str) -> None:
    assert _judged(fixtures, _figure("Fact", value, "crm/crm.json")) is None


def test_an_amount_written_as_money_inside_a_text_value_is_still_judged(fixtures: Path) -> None:
    assert _judged(fixtures, _figure("Fees", "$7000.00 / $228,659.62", "custodian/transactions.csv")) is None
    assert _judged(fixtures, _figure("Fees", "$7000.00 / $1,234.56", "custodian/transactions.csv")) is not None


# (f) a rounding of a figure the answer gives or the key computes


@pytest.mark.parametrize("prose", ["a gain of about $1,062", "a gain near $1.06k", "roughly $1,060"])
def test_prose_rounding_a_figure_the_answer_cites_is_accepted(fixtures: Path, prose: str) -> None:
    # T-MTG-04 basic and checklist: "$1,062" and "$1,060" beside a cited 1,061.56.
    gain = _figure("LQD unrealized gain", "1061.56", "custodian/tax_lots.csv")
    assert _judged(fixtures, gain, prose=f"LQD shows {prose}.") is None


def test_prose_rounding_a_key_figure_is_accepted(fixtures: Path) -> None:
    # T-CMP-01: "$440k" beside the key's 437,776.00.
    assert _judged(fixtures, prose="The sale realized about $440k.", key=("437776.00",)) is None
    assert _judged(fixtures, prose="The sale realized about $450k.", key=("437776.00",)) is not None


@pytest.mark.parametrize("prose", ["about $1,070", "about $1,100.00", "about $259k"])
def test_prose_that_rounds_nothing_the_answer_or_key_states_is_fabricated(fixtures: Path, prose: str) -> None:
    # "$259k" rounds 258,560.16, which is in a file but neither cited by the answer nor computed by the key.
    gain = _figure("LQD unrealized gain", "1061.56", "custodian/tax_lots.csv")
    assert _judged(fixtures, gain, prose=f"LQD shows {prose}.") is not None


@pytest.mark.parametrize(
    ("words", "unit"),
    [
        ("$440k", "10000"),
        ("$438k", "1000"),
        ("$187.5k", "100"),
        ("$430,000", "10000"),
        ("$1,062", "1"),
        ("$1,061.56", None),
    ],
)
def test_the_rounding_unit_is_read_from_how_the_amount_is_written(words: str, unit: str | None) -> None:
    assert rounding_unit(words) == (Decimal(unit) if unit else None)


# A note the run wrote in the CRM may repeat what its answer derived


def test_a_crm_note_repeating_a_figure_the_answer_derived_is_not_fabricated(fixtures: Path) -> None:
    # T-MTG-04 skill, repeat 1: the note repeated the IRA's value the answer had shown as a sum.
    derived = _figure("SYN-27490002 value incl. cash (258,560.16 + 27,200.00 + 1,463.16)", "287223.32", "custodian")
    support = Support(fixtures, [])
    answer = ("The IRA is worth $287,223.32.", (derived,))
    assert support.first_fabrication("Note: IRA value $287,223.32.", (), (), answer=answer) is None
    assert support.first_fabrication("Note: IRA value $287,323.32.", (), (), answer=answer) is not None


# Round 1 of the review (reviewers A and B)


def test_a_cited_figure_may_stand_on_arithmetic_the_answer_shows_outside_its_label(fixtures: Path) -> None:
    # A-S1, B-S1: the working in prose, the figure cited with a plain label.
    figure = _figure("Taxable part", "6785.71", "custodian/positions.csv")
    assert _judged(fixtures, figure, prose="Taxable: 7000 x (1 - 7000/228659.62) = 6785.71.") is None
    invented = _figure("Taxable part", "6785.09", "custodian/positions.csv")  # an operand in no file
    assert _judged(fixtures, invented, prose="Taxable: 7000 x (1 - 7000/228000.00) = 6785.09.") is not None


def test_a_price_label_with_no_number_in_its_text_is_no_figure(fixtures: Path) -> None:
    # A-S2, B-S2.
    assert _judged(fixtures, _figure("Price status", "not available", "custodian/positions.csv")) is None
    assert _judged(fixtures, _figure("IVV price", "$1,350.00", "custodian/positions.csv")) is not None
    # Reviewer A, round 2: a date in a price's text is no price.
    for text in ("2023-01-05", "not available on 2023-01-05"):
        assert _judged(fixtures, _figure("Price last reviewed", text, "custodian/positions.csv")) is None
    assert _judged(fixtures, _figure("IVV price", "$680.00 on 2026-04-15", "custodian/positions.csv")) is None
    assert _judged(fixtures, _figure("IVV price", "$681.00 on 2026-04-15", "custodian/positions.csv")) is not None


def test_prose_written_to_tenths_rounds_to_a_dime(fixtures: Path) -> None:
    # A-S3: "$1,061.6" beside a cited 1,061.56.
    gain = _figure("LQD unrealized gain", "1061.56", "custodian/tax_lots.csv")
    assert rounding_unit("$1,061.6") == Decimal("0.1")
    assert _judged(fixtures, gain, prose="LQD shows $1,061.6 of gain.") is None
    assert _judged(fixtures, gain, prose="LQD shows $1,062.6 of gain.") is not None


@pytest.mark.parametrize("value", ["1062.00", "1061.60", "1062"])
def test_a_result_written_to_the_cent_must_be_right_to_the_cent(fixtures: Path, value: str) -> None:
    # A-D1, B-D1: "1062.00" was read as written to the dollar, so 1,061.56 passed for it. Written "1062" it is
    # to the dollar, and passes as the arithmetic rounded; the others do not.
    figure = _figure("LQD gain (258,560.16 - 257,498.60)", value, "custodian/tax_lots.csv")
    assert (_judged(fixtures, figure) is None) is (value == "1062")
