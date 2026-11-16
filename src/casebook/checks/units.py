"""Opening units plus acquisitions minus disposals, adjusted for corporate actions, equal closing units and lots."""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

from casebook.model.dates import PRIOR_YEAR_END, SCENARIO_DATE
from casebook.model.files import (
    POSITIONS_CSV,
    TAX_LOTS_CSV,
    TRANSACTION_TYPES,
    TRANSACTIONS_CSV,
    UNIT_SIGNS,
    PositionRow,
    read_positions,
    read_tax_lots,
    read_transactions,
)

ZERO = Decimal(0)
type Key = tuple[str, str]


def check_units(root: Path) -> list[str]:
    problems: list[str] = []
    positions = read_positions(root)
    transactions = read_transactions(root)
    lots = read_tax_lots(root)
    by_day: dict[date, dict[Key, PositionRow]] = defaultdict(dict)
    for row in positions:
        key = (row.account_id, row.security_id)
        if key in by_day[row.valuation_date]:
            problems.append(f"{POSITIONS_CSV} line {row.line}: {key[0]} {key[1]} appears twice on {row.valuation_date}")
        by_day[row.valuation_date][key] = row
    for t in transactions:
        if t.type not in TRANSACTION_TYPES:
            problems.append(f"{TRANSACTIONS_CSV} line {t.line}: unknown transaction type {t.type!r}")
        elif t.type in UNIT_SIGNS and t.units is None and t.security_id:
            problems.append(f"{TRANSACTIONS_CSV} line {t.line}: {t.type} {t.transaction_id} has no units")
    days = sorted(by_day)
    if not days or days[0] != PRIOR_YEAR_END or days[-1] != SCENARIO_DATE:
        return [
            *problems,
            f"{POSITIONS_CSV}: needs the opening positions on {PRIOR_YEAR_END} and the closing positions on "
            f"{SCENARIO_DATE}; it has {', '.join(map(str, days)) or 'none'}",
        ]
    for start, end in pairwise(days):
        expected: dict[Key, Decimal] = defaultdict(Decimal)
        for key, row in by_day[start].items():
            expected[key] += row.units
        for t in transactions:
            if start < t.trade_date <= end and t.type in UNIT_SIGNS and t.units is not None:
                expected[(t.account_id, t.security_id)] += t.units * UNIT_SIGNS[t.type]
        for key in sorted(set(expected) | set(by_day[end])):
            row = by_day[end].get(key)
            actual = row.units if row else ZERO
            if actual != expected[key]:
                where = f"line {row.line}" if row else "no row"
                problems.append(
                    f"{POSITIONS_CSV} {where}: {key[0]} {key[1]} on {end} holds {actual}; "
                    f"{start} units and the transactions between give {expected[key]}"
                )
    lot_days: dict[date, dict[Key, Decimal]] = {day: defaultdict(Decimal) for day in (PRIOR_YEAR_END, SCENARIO_DATE)}
    for lot in lots:
        if lot.valuation_date not in lot_days:
            problems.append(
                f"{TAX_LOTS_CSV} line {lot.line}: lot {lot.lot_id} is dated {lot.valuation_date}; "
                f"lots are listed on {PRIOR_YEAR_END} and {SCENARIO_DATE}"
            )
            continue
        lot_days[lot.valuation_date][(lot.account_id, lot.security_id)] += lot.units
    for day, in_lots in lot_days.items():
        held = {key: row.units for key, row in by_day[day].items()}
        for key in sorted(set(held) | set(in_lots)):
            if held.get(key, ZERO) != in_lots[key]:
                problems.append(
                    f"{TAX_LOTS_CSV}: {key[0]} {key[1]} lots on {day} hold {in_lots[key]}, "
                    f"the position on {day} is {held.get(key, ZERO)}"
                )
    return problems
