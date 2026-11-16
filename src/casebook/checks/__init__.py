"""The checks every household must pass, and the check report. Reads emitted files only."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from casebook.checks.cash import check_cash
from casebook.checks.dates import check_dates
from casebook.checks.units import check_units
from casebook.model.files import FileFormatError, household_dir, read_manifest

type Check = Callable[[Path], list[str]]

CHECKS: dict[str, Check] = {
    "units": check_units,
    "cash": check_cash,
    "valuation date not after known-as-of": check_dates,
}


@dataclass(frozen=True)
class CheckLine:
    household_id: str
    check: str
    problems: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.problems


@dataclass(frozen=True)
class CheckReport:
    lines: tuple[CheckLine, ...]

    @property
    def passed(self) -> bool:
        return all(line.passed for line in self.lines)

    def failed_households(self) -> set[str]:
        return {line.household_id for line in self.lines if not line.passed}

    def render(self) -> str:
        width = max(len(name) for name in CHECKS)
        out: list[str] = []
        for line in self.lines:
            out.append(f"{line.household_id}  {line.check:<{width}}  {'pass' if line.passed else 'FAIL'}")
            out += [f"    {problem}" for problem in line.problems]
        failed = sum(not line.passed for line in self.lines)
        out.append(f"{len(self.lines)} lines: {len(self.lines) - failed} pass, {failed} fail")
        return "\n".join(out) + "\n"


def run_check(check: Check, root: Path) -> tuple[str, ...]:
    try:
        return tuple(check(root))
    except FileFormatError as error:
        return (str(error),)


def check_book(book_root: Path) -> CheckReport:
    manifest = read_manifest(book_root)
    lines = [
        CheckLine(household.household_id, name, run_check(check, book_root / household_dir(household.household_id)))
        for household in manifest.households
        for name, check in CHECKS.items()
    ]
    return CheckReport(tuple(lines))
