"""No background household crosses a drift, RMD or concentration threshold without a registry entry.

Featured households carry their situations by design; this check covers the generated ones.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from casebook.checks.book import registered, sealed_household
from casebook.model.dates import SCENARIO_DATE
from casebook.model.files import (
    ACCOUNTS_COLUMNS,
    ACCOUNTS_CSV,
    DISTRIBUTION,
    PORTFOLIO_HOUSEHOLD,
    PORTFOLIO_IPS,
    QCD,
    read_cash,
    read_csv,
    read_json,
    read_positions,
    read_transactions,
)
from casebook.model.money import parse_decimal

ZERO = Decimal(0)
BACKGROUND = "background"
# SECURE 2.0: an IRA owner born in 1952 or earlier owes a distribution for 2025, due by
# 1 April 2026 at the latest, so it is due before the scenario date.
RMD_BORN_BY = date(1952, 12, 31)
RMD_FROM, RMD_BY = date(2025, 1, 1), date(2026, 4, 1)


def check_thresholds(root: Path) -> list[str]:
    if sealed_household(root).get("set") != BACKGROUND:
        return []
    problems: list[str] = []

    def crossed(kind: str, what: str, ref: str) -> None:
        if not registered(root, kind=kind, refs=(ref,)):
            problems.append(f"crosses a {kind} threshold with no registry entry: {what}")

    ips = read_json(root, PORTFOLIO_IPS)
    classes = {str(c["security_id"]): str(c["asset_class"]) for c in ips["asset_classes"]}
    by_security: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for row in read_positions(root):
        if row.valuation_date == SCENARIO_DATE:
            by_security[row.security_id] += row.market_value
    cash = sum((c.settled_cash + c.unsettled_cash for c in read_cash(root) if c.valuation_date == SCENARIO_DATE), ZERO)
    total = sum(by_security.values(), ZERO) + cash
    if total <= 0:
        return [f"{ACCOUNTS_CSV}: the household is worth nothing on {SCENARIO_DATE}"]
    by_class: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for security, value in by_security.items():
        by_class[classes.get(security, "unclassified")] += value
    for target in ips["targets"]:
        weight = by_class[str(target["asset_class"])] / total
        aim, band = parse_decimal(str(target["target"])), parse_decimal(str(target["band"]))
        if abs(weight - aim) > band:
            what = f"{target['asset_class']} is {weight:.4f} of the household, target {aim} plus or minus {band}"
            crossed("drift", what, str(target["asset_class"]))
    limit = parse_decimal(str(ips["concentration_limit"]["share_of_household"]))
    for security, value in sorted(by_security.items()):
        if value / total > limit:
            crossed("concentration", f"{security} is {value / total:.4f} of the household, above {limit}", security)

    household = read_json(root, PORTFOLIO_HOUSEHOLD)
    born = {str(m["person_id"]): date.fromisoformat(str(m["born"])) for m in household["household_membership"]}
    owners = {str(o["account_id"]): [str(p) for p in o["owner_ids"]] for o in household["legal_ownership"]}
    paid = {
        t.account_id
        for t in read_transactions(root)
        if t.type in (DISTRIBUTION, QCD) and RMD_FROM <= t.trade_date <= RMD_BY and t.amount < 0
    }
    for account in read_csv(root, ACCOUNTS_CSV, ACCOUNTS_COLUMNS):
        if account["account_type"] != "traditional_ira" or account["account_id"] in paid:
            continue
        if any(born[p] <= RMD_BORN_BY for p in owners.get(account["account_id"], []) if p in born):
            crossed(
                "rmd",
                f"{account['account_id']} owes a 2025 distribution and shows none by {RMD_BY}",
                account["account_id"],
            )
    return problems
