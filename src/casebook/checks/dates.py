"""No observation's valuation date is later than its known-as-of date."""

import csv
import io
import json
from datetime import date
from pathlib import Path
from typing import Any

VALUATION = "valuation_date"
KNOWN = "known_as_of"


def _compare(where: str, valuation: object, known: object) -> str | None:
    if valuation is None or known is None:
        missing = VALUATION if valuation is None else KNOWN
        return f"{where}: has one of the two dates but no {missing}"
    try:
        v, k = date.fromisoformat(str(valuation)), date.fromisoformat(str(known))
    except ValueError:
        return f"{where}: {VALUATION} {valuation!r} or {KNOWN} {known!r} is not a date"
    if v > k:
        return f"{where}: {VALUATION} {v} is later than {KNOWN} {k}"
    return None


def _walk(value: Any, where: str, problems: list[str]) -> None:
    if isinstance(value, dict):
        if VALUATION in value or KNOWN in value:
            problem = _compare(where, value.get(VALUATION), value.get(KNOWN))
            if problem:
                problems.append(problem)
        for key, child in sorted(value.items()):
            _walk(child, f"{where}.{key}", problems)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk(child, f"{where}[{index}]", problems)


def check_dates(root: Path) -> list[str]:
    problems: list[str] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.suffix == ".csv":
            rows = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))
            for line, row in enumerate(rows, start=2):
                if VALUATION in row or KNOWN in row:
                    problem = _compare(f"{relative} line {line}", row.get(VALUATION), row.get(KNOWN))
                    if problem:
                        problems.append(problem)
        elif path.suffix == ".json":
            _walk(json.loads(path.read_text(encoding="utf-8")), relative, problems)
    return problems
