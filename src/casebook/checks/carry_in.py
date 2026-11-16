"""Carry-in history is present: acquisition dates, loss carryforwards, IRA basis, prior 31 December balances."""

from pathlib import Path

from casebook.model.dates import PRIOR_YEAR_END
from casebook.model.files import (
    ACCOUNTS_COLUMNS,
    ACCOUNTS_CSV,
    CASH_CSV,
    PORTFOLIO_HOUSEHOLD,
    PORTFOLIO_TAX_PROFILE,
    POSITIONS_CSV,
    TAX_LOTS_CSV,
    read_cash,
    read_csv,
    read_json,
    read_positions,
    read_tax_lots,
)
from casebook.model.money import parse_decimal

TRADITIONAL_IRA = "traditional_ira"


def check_carry_in(root: Path) -> list[str]:
    problems: list[str] = []
    accounts = read_csv(root, ACCOUNTS_CSV, ACCOUNTS_COLUMNS)
    opening_cash = {c.account_id for c in read_cash(root) if c.valuation_date == PRIOR_YEAR_END}
    for account in accounts:
        if account["account_id"] not in opening_cash:
            problems.append(f"{CASH_CSV}: account {account['account_id']} has no balance on {PRIOR_YEAR_END}")
    opening_lots = [lot for lot in read_tax_lots(root) if lot.valuation_date == PRIOR_YEAR_END]
    for lot in opening_lots:
        if lot.acquired_date > PRIOR_YEAR_END:
            problems.append(f"{TAX_LOTS_CSV} line {lot.line}: opening lot {lot.lot_id} is acquired {lot.acquired_date}")
    lotted = {(lot.account_id, lot.security_id) for lot in opening_lots}
    for position in read_positions(root):
        if position.valuation_date == PRIOR_YEAR_END and (position.account_id, position.security_id) not in lotted:
            problems.append(
                f"{POSITIONS_CSV} line {position.line}: {position.account_id} {position.security_id} has no opening "
                "lots, so its acquisition dates are missing"
            )
    household = read_json(root, PORTFOLIO_HOUSEHOLD)
    profile = read_json(root, PORTFOLIO_TAX_PROFILE)

    def amount(entry: dict[str, object], field: str, what: str) -> None:
        try:
            parse_decimal(str(entry[field]))
        except (KeyError, ValueError):
            problems.append(f"{PORTFOLIO_TAX_PROFILE}: {what} has no {field} amount")

    for c in profile["loss_carryforwards"]:
        for field in ("short_term", "long_term"):
            amount(c, field, f"tax unit {c.get('tax_unit_id')}'s loss carryforward")
    for b in profile["ira_basis"]:
        amount(b, "basis", f"IRA owner {b.get('person_id')}")
    carried = {str(c["tax_unit_id"]) for c in profile["loss_carryforwards"]}
    for unit in household["tax_units"]:
        if str(unit["tax_unit_id"]) not in carried:
            problems.append(f"{PORTFOLIO_TAX_PROFILE}: tax unit {unit['tax_unit_id']} has no loss carryforward")
    based = {str(b["person_id"]) for b in profile["ira_basis"]}
    iras = {a["account_id"] for a in accounts if a["account_type"] == TRADITIONAL_IRA}
    for owned in household["legal_ownership"]:
        if owned["account_id"] in iras:
            for person in owned["owner_ids"]:
                if str(person) not in based:
                    problems.append(f"{PORTFOLIO_TAX_PROFILE}: IRA owner {person} has no IRA basis")
    return problems
