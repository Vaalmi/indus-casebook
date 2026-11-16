"""No lot is oversold; basis rolls forward from the opening lots to the scenario date.

An independent roll-forward from the emitted files: the opening lots, the lots purchases and
vestings open, the lots the realized file closes, splits, moves in kind and step-ups. It
must arrive at the lots the custodian lists on the scenario date.
"""

import re
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from casebook.checks.book import book_prices
from casebook.model.dates import PRIOR_YEAR_END, SCENARIO_DATE
from casebook.model.files import (
    BUY,
    REALIZED_CSV,
    RSU_VEST,
    SELL,
    SPLIT,
    STEP_UP,
    TAX_LOTS_CSV,
    TRANSACTIONS_CSV,
    TRANSFER_IN,
    TRANSFER_OUT,
    RealizedRow,
    TransactionRow,
    read_realized,
    read_tax_lots,
    read_transactions,
)
from casebook.model.money import CENT, cents

ZERO = Decimal(0)
_SHARE = re.compile(r"share (\d+(?:\.\d+)?)$")


@dataclass(frozen=True)
class _Lot:
    account_id: str
    security_id: str
    acquired: date
    units: Decimal
    cost: Decimal


class _Rollforward:
    def __init__(self, root: Path, problems: list[str]) -> None:
        self.root = root
        self.problems = problems
        self.lots: dict[str, _Lot] = {}

    def held(self, account: str, security: str) -> list[tuple[str, _Lot]]:
        return sorted(
            ((i, x) for i, x in self.lots.items() if (x.account_id, x.security_id) == (account, security)),
            key=lambda pair: (pair[1].acquired, pair[0]),
        )

    def open_lot(self, t: TransactionRow) -> None:
        if not t.lot_id or t.units is None:
            self.problems.append(f"{TRANSACTIONS_CSV} line {t.line}: {t.type} {t.transaction_id} names no lot or units")
            return
        cost = -t.amount if t.type == BUY else cents(t.units * (t.price or ZERO))
        self.lots[t.lot_id] = _Lot(t.account_id, t.security_id, t.trade_date, t.units, cost)

    def close(self, t: TransactionRow, closed: list[RealizedRow]) -> None:
        if sum((r.units for r in closed), ZERO) != (t.units or ZERO):
            self.problems.append(
                f"{REALIZED_CSV}: sale {t.transaction_id} closes lots for other than its {t.units} units"
            )
        proceeds = sum((r.proceeds for r in closed), ZERO)
        # Each lot's share of the proceeds is rounded to the cent, so the parts may differ by a cent a lot.
        if abs(proceeds - t.amount) > CENT * len(closed):
            self.problems.append(
                f"{REALIZED_CSV}: sale {t.transaction_id} closes lots for {proceeds}, not its {t.amount}"
            )
        for r in closed:
            if r.gain != r.proceeds - r.cost_basis:
                self.problems.append(
                    f"{REALIZED_CSV} line {r.line}: lot {r.lot_id} gain {r.gain} is not proceeds {r.proceeds} "
                    f"less basis {r.cost_basis}"
                )
        for r in closed:
            lot = self.lots.get(r.lot_id)
            where = f"{REALIZED_CSV} line {r.line}: lot {r.lot_id} in {r.account_id}"
            if lot is None or (lot.account_id, lot.security_id) != (r.account_id, r.security_id):
                self.problems.append(f"{where} is not an open lot of {r.security_id} there")
                continue
            if r.units > lot.units:
                self.problems.append(f"{where} is oversold: {r.units} sold, {lot.units} held")
                continue
            relieved = lot.cost if r.units == lot.units else cents(lot.cost * r.units / lot.units)
            if r.cost_basis != relieved:
                self.problems.append(f"{where}: basis {r.cost_basis} relieved, the lot's basis gives {relieved}")
            if r.units == lot.units:
                del self.lots[r.lot_id]
            else:
                self.lots[r.lot_id] = replace(lot, units=lot.units - r.units, cost=lot.cost - relieved)

    def split(self, t: TransactionRow) -> None:
        held = self.held(t.account_id, t.security_id)
        before = sum((x.units for _, x in held), ZERO)
        if before == 0:
            self.problems.append(f"{TRANSACTIONS_CSV} line {t.line}: a split of {t.security_id} that is not held")
            return
        ratio = (before + (t.units or ZERO)) / before
        for lot_id, lot in held:
            self.lots[lot_id] = replace(lot, units=lot.units * ratio)

    def move(self, out: TransactionRow, into: TransactionRow) -> None:
        remaining = out.units or ZERO
        event_id = "E" + out.transaction_id.removeprefix("T")
        for lot_id, lot in self.held(out.account_id, out.security_id):
            if remaining == 0:
                break
            take = min(lot.units, remaining)
            if take == lot.units:
                self.lots[lot_id] = replace(lot, account_id=into.account_id)
            else:
                cost = cents(lot.cost * take / lot.units)
                self.lots[lot_id] = replace(lot, units=lot.units - take, cost=lot.cost - cost)
                self.lots[f"{lot_id}/{event_id}"] = _Lot(into.account_id, lot.security_id, lot.acquired, take, cost)
            remaining -= take
        if remaining:
            self.problems.append(f"{TRANSACTIONS_CSV} line {out.line}: moves more {out.security_id} than is held")

    def step_up(self, t: TransactionRow) -> None:
        found = _SHARE.search(t.description)
        if not found:
            self.problems.append(f"{TRANSACTIONS_CSV} line {t.line}: a step-up that does not state its share")
            return
        share = Decimal(found.group(1))
        prices = book_prices(self.root)
        for lot_id, lot in [(i, x) for i, x in self.lots.items() if x.account_id == t.account_id]:
            price = prices.get((lot.security_id, t.trade_date))
            if price is None:
                self.problems.append(
                    f"{TRANSACTIONS_CSV} line {t.line}: no price for {lot.security_id} on {t.trade_date}"
                )
                continue
            units = lot.units * share
            stepped = _Lot(lot.account_id, lot.security_id, t.trade_date, units, cents(units * price[0]))
            if share == 1:
                self.lots[lot_id] = stepped
            else:
                self.lots[f"{lot_id}-S"] = stepped
                self.lots[lot_id] = replace(lot, units=lot.units - units, cost=lot.cost - cents(lot.cost * share))


def check_lots(root: Path) -> list[str]:
    problems: list[str] = []
    lots = read_tax_lots(root)
    roll = _Rollforward(root, problems)
    for lot in lots:
        if lot.valuation_date == PRIOR_YEAR_END:
            roll.lots[lot.lot_id] = _Lot(lot.account_id, lot.security_id, lot.acquired_date, lot.units, lot.cost_basis)
    realized: dict[str, list[RealizedRow]] = {}
    for r in read_realized(root):
        realized.setdefault(r.transaction_id, []).append(r)
    transactions = read_transactions(root)
    pending_out: dict[str, TransactionRow] = {}
    for t in transactions:
        if t.type in (BUY, RSU_VEST):
            roll.open_lot(t)
        elif t.type == SELL:
            roll.close(t, realized.pop(t.transaction_id, []))
        elif t.type == SPLIT:
            roll.split(t)
        elif t.type == STEP_UP:
            roll.step_up(t)
        elif t.type == TRANSFER_OUT and t.security_id:
            pending_out[t.transaction_id] = t
        elif t.type == TRANSFER_IN and t.security_id:
            out = pending_out.pop(t.transaction_id, None)
            if out is None:
                problems.append(f"{TRANSACTIONS_CSV} line {t.line}: a transfer in with no transfer out")
            else:
                roll.move(out, t)
    for transaction, rows in realized.items():
        problems.append(f"{REALIZED_CSV} line {rows[0].line}: closes lots for {transaction}, which is not a sale")
    closing = {lot.lot_id: lot for lot in lots if lot.valuation_date == SCENARIO_DATE}
    for lot_id in sorted(set(closing) | set(roll.lots)):
        listed, expected = closing.get(lot_id), roll.lots.get(lot_id)
        if listed is None:
            problems.append(f"{TAX_LOTS_CSV}: lot {lot_id} should be open on {SCENARIO_DATE} and is not listed")
        elif expected is None:
            problems.append(f"{TAX_LOTS_CSV} line {listed.line}: lot {lot_id} is listed but no history opens it")
        else:
            got = (listed.account_id, listed.security_id, listed.acquired_date, listed.units, listed.cost_basis)
            want = (expected.account_id, expected.security_id, expected.acquired, expected.units, expected.cost)
            if got != want:
                problems.append(
                    f"{TAX_LOTS_CSV} line {listed.line}: lot {lot_id} is {got[3]} units, basis {got[4]}, "
                    f"acquired {got[2]} in {got[0]}; its history gives {want[3]} units, basis {want[4]}, "
                    f"acquired {want[2]} in {want[0]}"
                )
    return problems
