"""docs/PLAN.md, slice 7: every household's 2025 tax summary, and the comparison that holds the engine to
Tax-Calculator and to the keys. An altered summary fails it, one test per compared field."""

import dataclasses
import json
from decimal import Decimal
from pathlib import Path

import pytest

from casebook import build
from casebook.build import BuildError, build_book
from casebook.cli import main
from casebook.model.files import TAX_SUMMARY, read_json, read_manifest, tax_summary_path
from casebook.model.tax import TaxSummary, TaxUnitFacts, parse_summary
from casebook.tax.summary import BRACKET, KEYS, TAXCALC, TaxReport, book_units, compare, tax_report

from .conftest import SCRIPTS, SEED, built

D = Decimal
FIVE = ("agi", "bracket", "niit", "carryforward_short", "carryforward_long", "ira_basis")


def units_of(book: Path, *households: str) -> list[TaxUnitFacts]:
    return [unit for unit in book_units(book) if unit.household_id in households]


@pytest.fixture(scope="module")
def featured_report(book: Path) -> TaxReport:
    """HH-1204 (a backdoor conversion, so an IRA basis carried to 2026, and NIIT) and HH-9234 (a harvested
    long-term loss carried to 2026)."""
    return tax_report(units_of(book, "HH-1204", "HH-9234"))


def test_every_household_has_a_tax_summary_with_the_five_figures(full_book: Path) -> None:
    for household in built(full_book):
        stored = read_json(full_book, tax_summary_path(household))
        units = read_json(full_book, f"sealed/{household}/events.json")["tax_units"]
        assert stored["tax_year"] == 2025
        assert [s["tax_unit_id"] for s in stored["summaries"]] == [u["tax_unit_id"] for u in units], household
        for raw in stored["summaries"]:
            assert set(FIVE) <= set(raw), household
            summary = parse_summary(raw)
            assert summary.calculator == "engine"
            # Each person with a traditional IRA, or basis on file, has a basis carried to 2026.
            people = {i["person_id"] for u in units if u["tax_unit_id"] == raw["tax_unit_id"] for i in u["iras"]}
            assert {p for p, _ in summary.ira_basis} == people, household


def test_the_engine_agrees_with_tax_calculator_and_the_keys_on_every_household(full_book: Path) -> None:
    compared: set[tuple[str, str]] = set()
    for household in built(full_book):
        stored = read_json(full_book, tax_summary_path(household))
        for comparison in stored["comparisons"]:
            assert comparison["agrees"], (household, comparison)
            compared.add((comparison["field"].split()[0], comparison["against"]))
        fields = {(c["tax_unit_id"], c["field"]) for c in stored["comparisons"]}
        for unit in stored["summaries"]:
            for field in ("agi", "income_tax", "niit", BRACKET, "carryforward_short", "carryforward_long"):
                assert (unit["tax_unit_id"], field) in fields, (household, field)
    assert compared == {
        ("agi", TAXCALC),
        ("income_tax", TAXCALC),
        ("niit", TAXCALC),
        (BRACKET, TAXCALC),
        ("carryforward_short", KEYS),
        ("carryforward_long", KEYS),
        ("ira_basis", KEYS),
    }


def test_every_household_has_a_composite_1099(full_book: Path) -> None:
    for household in built(full_book):
        index = read_json(full_book, f"households/{household}/documents/index.json")["documents"]
        assert any(entry["kind"] == "form_1099_composite" for entry in index), household


def test_the_featured_figures_agree_before_any_change(featured_report: TaxReport) -> None:
    assert featured_report.agrees, featured_report.render()
    (backdoor,) = [s for s in featured_report.summaries if s.household_id == "HH-1204"]
    (harvested,) = [s for s in featured_report.summaries if s.household_id == "HH-9234"]
    assert backdoor.ira_basis != () and any(basis > 0 for _, basis in backdoor.ira_basis)
    assert backdoor.niit > 0
    assert harvested.carryforward_long > 0


def altered(report: TaxReport, household: str, **change: object) -> list[tuple[str, str, str]]:
    """The disagreements once one engine summary has one field changed."""
    summaries = [
        dataclasses.replace(s, **change) if s.household_id == household else s  # type: ignore[arg-type]
        for s in report.summaries
    ]
    return [
        (c.household_id, c.field, c.against) for c in compare(summaries, report.crosscheck, report.keys) if not c.agrees
    ]


def one(report: TaxReport, household: str) -> TaxSummary:
    (summary,) = [s for s in report.summaries if s.household_id == household]
    return summary


def test_income_altered_fails_the_comparison(featured_report: TaxReport) -> None:
    agi = one(featured_report, "HH-1204").agi
    assert altered(featured_report, "HH-1204", agi=agi + D("2.01")) == [("HH-1204", "agi", TAXCALC)]
    # Within the two dollars, it still agrees.
    assert altered(featured_report, "HH-1204", agi=agi + D("2.00")) == []


def test_bracket_altered_fails_the_comparison(featured_report: TaxReport) -> None:
    assert one(featured_report, "HH-1204").bracket == D("0.24")
    assert altered(featured_report, "HH-1204", bracket=D("0.32")) == [("HH-1204", BRACKET, TAXCALC)]


def test_net_investment_income_tax_altered_fails_the_comparison(featured_report: TaxReport) -> None:
    niit = one(featured_report, "HH-1204").niit
    assert altered(featured_report, "HH-1204", niit=niit - D("2.01")) == [("HH-1204", "niit", TAXCALC)]


def test_loss_carryforwards_altered_fail_the_comparison(featured_report: TaxReport) -> None:
    long = one(featured_report, "HH-9234").carryforward_long
    assert altered(featured_report, "HH-9234", carryforward_long=long + D(3)) == [
        ("HH-9234", "carryforward_long", KEYS)
    ]
    assert altered(featured_report, "HH-9234", carryforward_short=D("2.50")) == [
        ("HH-9234", "carryforward_short", KEYS)
    ]


def test_ira_basis_altered_fails_the_comparison(featured_report: TaxReport) -> None:
    ((person, basis),) = one(featured_report, "HH-1204").ira_basis
    assert altered(featured_report, "HH-1204", ira_basis=((person, basis - D(5)),)) == [
        ("HH-1204", f"ira_basis {person}", KEYS)
    ]
    # A person dropped from the engine's summary is a disagreement too, not a silent pass.
    assert altered(featured_report, "HH-1204", ira_basis=()) == [("HH-1204", f"ira_basis {person}", KEYS)]


def test_the_build_refuses_a_book_whose_calculators_disagree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = build.tax_report

    def off_by_three(units: list[TaxUnitFacts]) -> TaxReport:
        report = real(units)
        first = dataclasses.replace(report.summaries[0], agi=report.summaries[0].agi + 3)
        summaries = (first, *report.summaries[1:])
        return dataclasses.replace(
            report, summaries=summaries, comparisons=tuple(compare(summaries, report.crosscheck, report.keys))
        )

    monkeypatch.setattr(build, "tax_report", off_by_three)
    with pytest.raises(BuildError, match=r"the tax calculators disagree:\n  TU-\d{4}-1 agi: .*DISAGREE"):
        build_book(SEED, tmp_path / "book", SCRIPTS)


def test_the_tax_command_lists_each_household_s_figures(book: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["tax", "--book", str(book)]) == 0
    out = capsys.readouterr().out
    households = [line for line in out.splitlines() if line.startswith("HH-")]
    assert households == list(built(book))
    assert "  TU-1204-1 bracket: engine 24%, taxcalc 24%: agree" in out
    assert out.rstrip().endswith(" 0 disagreements")


def test_the_site_leaves_out_the_tax_summaries(book: Path, site: Path) -> None:
    summaries = [name for name in read_manifest(book).files if name.endswith(TAX_SUMMARY)]
    assert len(summaries) == len(built(book))
    published = [p for p in site.rglob(TAX_SUMMARY)]
    assert published == []
    # The event logs, with the tax facts in them, are published as before.
    assert any(json.loads(p.read_text()).get("tax_units") for p in site.rglob("events.json"))
