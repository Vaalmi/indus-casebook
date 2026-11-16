"""The answer key for T-REC-06: which households' custodian positions and cash disagree with the portfolio
system on the as-of date.

For each household of the book it compares, as known on the as-of date, the custodian's positions valued that
day (custodian/positions.csv: units, price and market value per account and security) and its cash (settled
plus unsettled, custodian/cash.csv) with the portfolio system's (portfolio/positions.json). A household is
found when any holding or cash balance differs, or is held in one source only; its evidence is the accounts
that differ. It is unresolved when either source states nothing valued on the as-of date, so there is nothing
to compare.

The figures are what an answer may add up from either source: each account's positions, cash and value, and
the household's totals, in each source; and for a difference, the custodian's figure minus the portfolio's.
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from casebook.keys.figures import KeyFigure
from casebook.model.dates import parse_date
from casebook.model.files import (
    CASH_COLUMNS,
    CASH_CSV,
    PORTFOLIO_POSITIONS,
    POSITIONS_COLUMNS,
    POSITIONS_CSV,
    household_dir,
    read_csv,
    read_json,
    read_manifest,
)
from casebook.model.money import fmt, parse_decimal

CUSTODIAN, PORTFOLIO = "custodian", "portfolio system"
CASH = "cash"
KNOWN = "known_as_of"
ZERO = Decimal(0)

# A holding as (units, price, market value); cash as one amount.
type Holding = tuple[Decimal, Decimal, Decimal]


@dataclass(frozen=True)
class Difference:
    """One holding or cash balance the two sources state differently on the as-of date; None where a source
    has no line for it."""

    account_id: str
    item: str  # a security ID, or "cash"
    custodian: tuple[Decimal, ...] | None
    portfolio: tuple[Decimal, ...] | None


@dataclass(frozen=True)
class HouseholdFigures:
    household_id: str
    figures: tuple[KeyFigure, ...]


@dataclass(frozen=True)
class PositionsKey:
    as_of: date
    checked: tuple[str, ...]
    differences: tuple[tuple[str, tuple[Difference, ...]], ...]  # by household, only those that differ
    unresolved: tuple[str, ...]
    household_figures: tuple[HouseholdFigures, ...]

    @property
    def found(self) -> Mapping[str, tuple[str, ...]]:
        return {h: tuple(sorted({d.account_id for d in diffs})) for h, diffs in self.differences}

    @property
    def computed_figures(self) -> tuple[KeyFigure, ...]:
        return tuple(f for h in self.household_figures for f in h.figures)

    def to_dict(self) -> dict[str, Any]:
        def shown(values: tuple[Decimal, ...] | None) -> list[str] | None:
            return None if values is None else [fmt(v) for v in values]

        return {
            "as_of": self.as_of.isoformat(),
            "checked": list(self.checked),
            "found": {h: list(ids) for h, ids in self.found.items()},
            "unresolved": list(self.unresolved),
            "differences": {
                h: [
                    {
                        "account_id": d.account_id,
                        "item": d.item,
                        "custodian": shown(d.custodian),
                        "portfolio": shown(d.portfolio),
                    }
                    for d in diffs
                ]
                for h, diffs in self.differences
            },
            "computed_figures": {
                h.household_id: [{"label": f.label, "value": fmt(f.value)} for f in h.figures]
                for h in self.household_figures
            },
        }


@dataclass(frozen=True)
class _Source:
    holdings: dict[tuple[str, str], Holding]
    cash: dict[str, Decimal]

    @property
    def empty(self) -> bool:
        return not self.holdings and not self.cash


def _on(row: Mapping[str, Any], as_of: date) -> bool:
    return parse_date(str(row["valuation_date"])) == as_of and parse_date(str(row[KNOWN])) <= as_of


def _holding(row: Mapping[str, Any]) -> Holding:
    units, price, value = (parse_decimal(str(row[f])) for f in ("units", "price", "market_value"))
    return units, price, value


def _custodian(root: Path, as_of: date) -> _Source:
    holdings = {
        (r["account_id"], r["security_id"]): _holding(r)
        for r in read_csv(root, POSITIONS_CSV, POSITIONS_COLUMNS)
        if _on(r, as_of)
    }
    cash = {
        r["account_id"]: parse_decimal(r["settled_cash"]) + parse_decimal(r["unsettled_cash"])
        for r in read_csv(root, CASH_CSV, CASH_COLUMNS)
        if _on(r, as_of)
    }
    return _Source(holdings, cash)


def _portfolio(root: Path, as_of: date) -> _Source:
    raw = read_json(root, PORTFOLIO_POSITIONS)
    holdings = {(str(p["account_id"]), str(p["security_id"])): _holding(p) for p in raw["positions"] if _on(p, as_of)}
    cash = {str(c["account_id"]): parse_decimal(str(c["cash"])) for c in raw["cash"] if _on(c, as_of)}
    return _Source(holdings, cash)


def _differences(custodian: _Source, portfolio: _Source) -> tuple[Difference, ...]:
    found: list[Difference] = []
    for account, security in sorted(set(custodian.holdings) | set(portfolio.holdings)):
        held, listed = custodian.holdings.get((account, security)), portfolio.holdings.get((account, security))
        if held != listed:
            found.append(Difference(account, security, held, listed))
    for account in sorted(set(custodian.cash) | set(portfolio.cash)):
        held_cash, listed_cash = custodian.cash.get(account), portfolio.cash.get(account)
        if held_cash != listed_cash:
            found.append(
                Difference(
                    account,
                    CASH,
                    None if held_cash is None else (held_cash,),
                    None if listed_cash is None else (listed_cash,),
                )
            )
    return tuple(found)


def _source_figures(source: _Source, name: str) -> list[KeyFigure]:
    positions: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for (account, _), (_, _, value) in source.holdings.items():
        positions[account] += value
    figures: list[KeyFigure] = []
    for account in sorted(set(positions) | set(source.cash)):
        held, cash = positions[account], source.cash.get(account, ZERO)
        figures += [
            KeyFigure(f"{name} {account} positions value", held),
            KeyFigure(f"{name} {account} cash", cash),
            KeyFigure(f"{name} {account} value", held + cash),
        ]
    total_positions = sum(positions.values(), ZERO)
    total_cash = sum(source.cash.values(), ZERO)
    figures += [
        KeyFigure(f"{name} positions value", total_positions),
        KeyFigure(f"{name} cash", total_cash),
        KeyFigure(f"{name} total value", total_positions + total_cash),
    ]
    return figures


def _difference_figures(differences: tuple[Difference, ...]) -> list[KeyFigure]:
    figures: list[KeyFigure] = []
    for d in differences:
        if d.custodian is None or d.portfolio is None:
            continue
        names = (CASH,) if d.item == CASH else (f"{d.item} units", f"{d.item} price", f"{d.item} value")
        figures += [
            KeyFigure(f"{d.account_id} {name} difference", held - listed)
            for name, held, listed in zip(names, d.custodian, d.portfolio, strict=True)
        ]
    return figures


def positions_key(book: Path, as_of: date) -> PositionsKey:
    checked = tuple(sorted(h.household_id for h in read_manifest(book).households))
    differences: list[tuple[str, tuple[Difference, ...]]] = []
    unresolved: list[str] = []
    household_figures: list[HouseholdFigures] = []
    for household_id in checked:
        root = book / household_dir(household_id)
        custodian, portfolio = _custodian(root, as_of), _portfolio(root, as_of)
        if custodian.empty or portfolio.empty:
            unresolved.append(household_id)
            continue
        found = _differences(custodian, portfolio)
        if found:
            differences.append((household_id, found))
        figures = _source_figures(custodian, CUSTODIAN) + _source_figures(portfolio, PORTFOLIO)
        household_figures.append(HouseholdFigures(household_id, tuple(figures + _difference_figures(found))))
    return PositionsKey(as_of, checked, tuple(differences), tuple(unresolved), tuple(household_figures))
