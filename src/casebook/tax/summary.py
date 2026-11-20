"""The 2025 tax summary per household, and the comparison that holds it to two other calculators.

A household's summary is the in-house engine's. Tax-Calculator recomputes income, tax and net
investment income tax and the bracket from the same tax-unit facts, except the taxable part of IRA,
401(k) and inherited-IRA distributions, which it takes from the keys' own Form 8606 (so for a unit
with a distribution or conversion, income agrees engine against keys there); the keys' own Form 8606 and
Capital Loss Carryover Worksheet recompute each person's IRA basis and the loss carried to 2026,
which no outside tool computes. A figure more than $2 apart, or a different bracket, is a
disagreement, and the build refuses a book with one (SPEC: "Two calculators agree on each summary
within 2 dollars").
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from casebook.keys.tax_lines import capital_loss_carryover, form_8606, taxable_retirement
from casebook.model.files import event_log_path, read_json, read_manifest
from casebook.model.money import usd
from casebook.model.tax import TaxSummary, TaxUnitFacts, parse_facts
from casebook.tax import crosscheck
from casebook.tax.engine import compute

TOLERANCE = Decimal(2)
TAXCALC, KEYS = crosscheck.CALCULATOR, "keys"
BRACKET = "bracket"
# Compared with Tax-Calculator: each within the tolerance, and the bracket equal.
WITH_TAXCALC = ("agi", "income_tax", "niit", BRACKET)
# Compared with the keys: the loss carried to 2026, and each person's IRA basis.
WITH_KEYS = ("carryforward_short", "carryforward_long")
IRA_BASIS = "ira_basis"


@dataclass(frozen=True)
class KeyFigures:
    """The keys' figures for one tax unit: the loss carried to 2026 and each person's IRA basis."""

    tax_unit_id: str
    carryforward_short: Decimal
    carryforward_long: Decimal
    ira_basis: tuple[tuple[str, Decimal], ...]


@dataclass(frozen=True)
class Comparison:
    """One figure as the engine has it and as the other calculator has it."""

    household_id: str
    tax_unit_id: str
    field: str  # a summary field, or "ira_basis <person ID>"
    against: str  # TAXCALC or KEYS
    engine: Decimal | None  # None: the engine has no figure for this person
    other: Decimal | None

    @property
    def agrees(self) -> bool:
        if self.engine is None or self.other is None:
            return False
        if self.field == BRACKET:
            return self.engine == self.other
        return abs(self.engine - self.other) <= TOLERANCE

    def render(self) -> str:
        def shown(value: Decimal | None) -> str:
            if value is None:
                return "none"
            return f"{value:.0%}" if self.field == BRACKET else usd(value)

        verdict = "agree" if self.agrees else "DISAGREE"
        difference = (
            ""
            if self.engine is None or self.other is None or self.field == BRACKET
            else f", difference {usd(self.engine - self.other)}"
        )
        return (
            f"  {self.tax_unit_id} {self.field}: engine {shown(self.engine)}, {self.against} "
            f"{shown(self.other)}{difference}: {verdict}"
        )


@dataclass(frozen=True)
class TaxReport:
    summaries: tuple[TaxSummary, ...]  # the engine's: each tax unit's summary, as the book keeps it
    crosscheck: tuple[TaxSummary, ...]
    keys: tuple[KeyFigures, ...]
    comparisons: tuple[Comparison, ...]

    @property
    def disagreements(self) -> list[Comparison]:
        return [c for c in self.comparisons if not c.agrees]

    @property
    def agrees(self) -> bool:
        return not self.disagreements

    def render(self) -> str:
        """Each household's comparisons, one line a figure, and a closing count."""
        lines: list[str] = []
        household = ""
        for comparison in self.comparisons:
            if comparison.household_id != household:
                household = comparison.household_id
                lines.append(household)
            lines.append(comparison.render())
        units = len(self.summaries)
        lines.append(
            f"{units} tax units, {len(self.comparisons)} figures compared, {len(self.disagreements)} disagreements"
        )
        return "\n".join(lines)


def key_figures(facts: TaxUnitFacts, crosschecked: TaxSummary) -> KeyFigures:
    """The keys' Form 8606 for each person, and the carryover worksheet run on Tax-Calculator's taxable
    income before its floor at zero (AGI less deductions) and its senior deduction, so no engine figure
    enters the keys'."""
    short, long = capital_loss_carryover(
        facts, crosschecked.agi - crosschecked.deductions, crosschecked.senior_deduction
    )
    return KeyFigures(
        tax_unit_id=facts.tax_unit_id,
        carryforward_short=short,
        carryforward_long=long,
        ira_basis=tuple((flows.person_id, form_8606(flows).basis_carried) for flows in facts.iras),
    )


def compare(
    summaries: Sequence[TaxSummary], crosschecked: Sequence[TaxSummary], keys: Sequence[KeyFigures]
) -> list[Comparison]:
    """Every compared figure for every tax unit, in the units' order. The three sequences are by tax unit,
    in the same order."""
    comparisons: list[Comparison] = []
    for engine, other, key in zip(summaries, crosschecked, keys, strict=True):
        if not engine.tax_unit_id == other.tax_unit_id == key.tax_unit_id:
            raise ValueError(f"tax units out of order: {engine.tax_unit_id}, {other.tax_unit_id}, {key.tax_unit_id}")
        ids = (engine.household_id, engine.tax_unit_id)
        for field in WITH_TAXCALC:
            comparisons.append(Comparison(*ids, field, TAXCALC, getattr(engine, field), getattr(other, field)))
        for field in WITH_KEYS:
            comparisons.append(Comparison(*ids, field, KEYS, getattr(engine, field), getattr(key, field)))
        engine_basis, key_basis = dict(engine.ira_basis), dict(key.ira_basis)
        for person in sorted(engine_basis.keys() | key_basis.keys()):
            comparisons.append(
                Comparison(*ids, f"{IRA_BASIS} {person}", KEYS, engine_basis.get(person), key_basis.get(person))
            )
    return comparisons


def tax_report(units: Sequence[TaxUnitFacts]) -> TaxReport:
    """Each unit through the engine, Tax-Calculator (one batch) and the keys, and the comparison."""
    summaries = [compute(unit).summary for unit in units]
    crosschecked = crosscheck.crosscheck(units, {unit.tax_unit_id: taxable_retirement(unit) for unit in units})
    keys = [key_figures(unit, other) for unit, other in zip(units, crosschecked, strict=True)]
    return TaxReport(
        summaries=tuple(summaries),
        crosscheck=tuple(crosschecked),
        keys=tuple(keys),
        comparisons=tuple(compare(summaries, crosschecked, keys)),
    )


def book_units(book: Path) -> list[TaxUnitFacts]:
    """Every tax unit's facts as a built book's sealed event logs hold them, in household order."""
    return [
        parse_facts(raw)
        for household in read_manifest(book).households
        for raw in read_json(book, event_log_path(household.household_id))["tax_units"]
    ]
