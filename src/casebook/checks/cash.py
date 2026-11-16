"""Closing cash equals opening cash plus the signed settled cash flows between."""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

from casebook.model.dates import PRIOR_YEAR_END, SCENARIO_DATE
from casebook.model.files import CASH_CSV, CashRow, read_accounts, read_cash, read_transactions

ZERO = Decimal(0)


def check_cash(root: Path) -> list[str]:
    problems: list[str] = []
    cash = read_cash(root)
    transactions = read_transactions(root)
    by_day: dict[date, dict[str, CashRow]] = defaultdict(dict)
    for row in cash:
        if row.account_id in by_day[row.valuation_date]:
            problems.append(f"{CASH_CSV} line {row.line}: {row.account_id} appears twice on {row.valuation_date}")
        by_day[row.valuation_date][row.account_id] = row
    days = sorted(by_day)
    if not days or days[0] != PRIOR_YEAR_END or days[-1] != SCENARIO_DATE:
        return [
            *problems,
            f"{CASH_CSV}: needs the opening balance on {PRIOR_YEAR_END} and the closing balance on {SCENARIO_DATE}; "
            f"it has {', '.join(map(str, days)) or 'none'}",
        ]
    for account in sorted(a.account_id for a in read_accounts(root)):
        missing = [str(day) for day in days if account not in by_day[day]]
        if missing:
            problems.append(f"{CASH_CSV}: account {account} has no balance on {', '.join(missing)}")
    for start, end in pairwise(days):
        for account in sorted(set(by_day[start]) | set(by_day[end])):
            before = by_day[start].get(account)
            after = by_day[end].get(account)
            if before is None or after is None:
                problems.append(f"{CASH_CSV}: {account} has no balance on {start if before is None else end}")
                continue
            settled = sum(
                (t.amount for t in transactions if t.account_id == account and start < t.settle_date <= end), ZERO
            )
            traded = sum(
                (t.amount for t in transactions if t.account_id == account and start < t.trade_date <= end), ZERO
            )
            expected = before.settled_cash + settled
            if after.settled_cash != expected:
                problems.append(
                    f"{CASH_CSV} line {after.line}: {account} settled cash on {end} is {after.settled_cash}; "
                    f"{before.settled_cash} on {start} plus {settled} settled between gives {expected}"
                )
            total_after = after.settled_cash + after.unsettled_cash
            total_before = before.settled_cash + before.unsettled_cash
            if total_after != total_before + traded:
                problems.append(
                    f"{CASH_CSV} line {after.line}: {account} settled plus unsettled cash on {end} is {total_after}; "
                    f"{total_before} on {start} plus {traded} traded between gives {total_before + traded}"
                )
    return problems
