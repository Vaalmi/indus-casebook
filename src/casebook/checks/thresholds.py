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
# 1 April 2026 at the latest, so it is due before the scenario date. The same holds for a former
# employer's 401(k), from the plan itself.
RMD_BORN_BY = date(1952, 12, 31)
RMD_FROM, RMD_BY = date(2025, 1, 1), date(2026, 4, 1)
YEAR_END = date(2025, 12, 31)
IRA, PLAN, INHERITED = "traditional_ira", "401k", "inherited_ira"


def required_beginning(born: date) -> date:
    """1 April after the year an owner reaches the applicable age: 70½ for those born before 1 July
    1949, 72 for those born then to 1950, 73 for 1951 to 1959, 75 from 1960 (26 U.S.C. §
    401(a)(9)(C), as the SECURE Act and SECURE 2.0 Act set it). The check's own rule, apart from the
    planters', so the two can disagree."""
    if born < date(1949, 7, 1):
        half = born.month + 6
        reached = born.year + 70 + (1 if half > 12 else 0)
        return date(reached + 1, 4, 1)
    age = 72 if born.year <= 1950 else 73 if born.year <= 1959 else 75
    return date(born.year + age + 1, 4, 1)


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
    accounts = read_csv(root, ACCOUNTS_CSV, ACCOUNTS_COLUMNS)
    kind_of = {a["account_id"]: a["account_type"] for a in accounts}
    paid_on = [
        (t.account_id, t.trade_date) for t in read_transactions(root) if t.type in (DISTRIBUTION, QCD) and t.amount < 0
    ]
    paid = {a for a, day in paid_on if RMD_FROM <= day <= RMD_BY}
    # An owner's IRA RMDs may be taken from any of the owner's traditional IRAs (26 CFR 1.408-8),
    # so one such IRA's distribution meets the threshold for all of them; a 401(k)'s or an inherited
    # IRA's distribution does not.
    ira_paid_by = {p for a in paid if kind_of.get(a) == IRA for p in owners.get(a, [])}
    for account in accounts:
        account_id, kind = account["account_id"], account["account_type"]
        holders = owners.get(account_id, [])
        of_age = any(born[p] <= RMD_BORN_BY for p in holders if p in born)
        if kind == IRA and of_age and not set(holders) <= ira_paid_by:
            crossed("rmd", f"{account_id} owes a 2025 distribution and shows none by {RMD_BY}", account_id)
        elif kind == PLAN and of_age and account_id not in paid:
            crossed(
                "rmd", f"{account_id}, a 401(k), owes its own 2025 distribution and shows none by {RMD_BY}", account_id
            )
        elif kind == INHERITED and account["decedent_born"] and account["decedent_died"]:
            # Under the ten-year rule, a decedent who died on or after the required beginning date
            # leaves annual distributions due from the year after death (26 CFR 1.401(a)(9)-5(d)).
            died = date.fromisoformat(account["decedent_died"])
            due = died >= required_beginning(date.fromisoformat(account["decedent_born"])) and died.year < 2025
            taken = any(a == account_id and RMD_FROM <= day <= YEAR_END for a, day in paid_on)
            if due and not taken:
                what = f"{account_id}, an inherited IRA, owes a 2025 distribution and shows none by {YEAR_END}"
                crossed("rmd", what, account_id)
    return problems
