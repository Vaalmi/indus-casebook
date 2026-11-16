"""What a check may read beside a household's own files: the book's registry, households list and prices."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from casebook.model.dates import parse_date
from casebook.model.files import (
    PRICES_COLUMNS,
    PRICES_CSV,
    REGISTRY,
    SEALED_HOUSEHOLDS,
    SECURITIES_COLUMNS,
    SECURITIES_CSV,
    read_csv,
    read_json,
)
from casebook.model.money import parse_decimal
from casebook.model.registry import RegistryEntry, parse_entry


def book_root(household_root: Path) -> Path:
    return household_root.parent.parent


def household_id(household_root: Path) -> str:
    return household_root.name


def registry_entries(household_root: Path) -> list[RegistryEntry]:
    entries = [parse_entry(e) for e in read_json(book_root(household_root), REGISTRY)["entries"]]
    return [e for e in entries if e.household_id == household_id(household_root)]


def registered(household_root: Path, *sources: str, kind: str | None = None, refs: tuple[str, ...] = ()) -> bool:
    """Whether a registry entry for this household names these sources, the kind if given, and these records."""
    for entry in registry_entries(household_root):
        if (
            set(sources) <= set(entry.sources)
            and (kind is None or kind in entry.item_type or kind in entry.crosses)
            and set(refs) <= set(entry.references)
        ):
            return True
    return False


def book_securities(household_root: Path) -> dict[str, str]:
    """How the book names each security (alias, or ticker in real-ticker mode), to its internal ID."""
    rows = read_csv(book_root(household_root), SECURITIES_CSV, SECURITIES_COLUMNS)
    return {r["security"]: r["security_id"] for r in rows}


def sealed_household(household_root: Path) -> dict[str, Any]:
    households = read_json(book_root(household_root), SEALED_HOUSEHOLDS)["households"]
    return next(h for h in households if h["household_id"] == household_id(household_root))


def book_price_rows(household_root: Path) -> list[tuple[str, date, Decimal, int]]:
    """Every row of the book's synthetic price series: security, date, price, line."""
    rows = read_csv(book_root(household_root), PRICES_CSV, PRICES_COLUMNS)
    return [
        (r["security_id"], parse_date(r["valuation_date"]), parse_decimal(r["price"]), i)
        for i, r in enumerate(rows, start=2)
    ]


def book_prices(household_root: Path) -> dict[tuple[str, date], tuple[Decimal, int]]:
    """The book's synthetic price series: (security, date) to (price, line); the prices check refuses duplicates."""
    return {(security, day): (price, line) for security, day, price, line in book_price_rows(household_root)}
