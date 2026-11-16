"""No loss sale has a repurchase within 30 days either side, across taxpayer, spouse and IRA accounts.

Unless planted: a wash sale with a registry entry passes.
"""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from casebook.checks.book import registered
from casebook.model.files import (
    BUY,
    PORTFOLIO_HOUSEHOLD,
    REALIZED_CSV,
    RSU_VEST,
    TRANSACTIONS_CSV,
    read_json,
    read_realized,
    read_transactions,
)

WINDOW = timedelta(days=30)
WASH_SALE = "wash_sale"


SPOUSES = {"primary", "spouse"}


def related_accounts(root: Path) -> dict[str, set[str]]:
    """Each account, with every account owned by its owners, their spouses, or anyone in their tax units.

    A spouse's purchase counts whether or not the couple files together.
    """
    household = read_json(root, PORTFOLIO_HOUSEHOLD)
    owners = {str(o["account_id"]): {str(p) for p in o["owner_ids"]} for o in household["legal_ownership"]}
    units = [{str(p) for p in t["person_ids"]} for t in household["tax_units"]]
    married = {str(m["person_id"]) for m in household["household_membership"] if m["relationship"] in SPOUSES}
    related: dict[str, set[str]] = {}
    for account, people in owners.items():
        circle = set(people).union(*(u for u in units if u & people))
        if people & married and len(married) == 2:
            circle |= married
        related[account] = {a for a, others in owners.items() if others & circle}
    return related


def check_wash_sales(root: Path) -> list[str]:
    problems: list[str] = []
    related = related_accounts(root)
    purchases = [t for t in read_transactions(root) if t.type in (BUY, RSU_VEST)]
    # The loss is proceeds less basis, worked out here; the file's gain column is not trusted for it.
    realized = read_realized(root)
    for sale in (r for r in realized if r.proceeds - r.cost_basis < 0):
        accounts = related.get(sale.account_id, {sale.account_id})
        for buy in purchases:
            # A purchase replaces only the shares of it still held after the loss sale: those of its lot sold
            # by then (the loss sale's own included) replace nothing.
            sold_by_then = sum(
                (r.units for r in realized if r.lot_id == buy.lot_id and r.sold_date <= sale.sold_date), Decimal(0)
            )
            replacing = (buy.units or 0) - sold_by_then
            if (
                buy.security_id == sale.security_id
                and buy.account_id in accounts
                and abs(buy.trade_date - sale.sold_date) <= WINDOW
                and replacing > 0
                and not registered(
                    root, REALIZED_CSV, TRANSACTIONS_CSV, kind=WASH_SALE, refs=(sale.transaction_id, buy.transaction_id)
                )
            ):
                problems.append(
                    f"{REALIZED_CSV} line {sale.line}: a loss on {sale.security_id} in {sale.account_id} on "
                    f"{sale.sold_date}, and {TRANSACTIONS_CSV} line {buy.line} buys it in {buy.account_id} on "
                    f"{buy.trade_date}, with no registry entry for the wash sale"
                )
    return problems
