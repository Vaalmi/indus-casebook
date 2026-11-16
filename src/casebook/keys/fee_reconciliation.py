"""The answer key for a fee reconciliation task: what one quarter's advisory fees should have been.

It reads only the household's emitted files. Billing groups come from the portfolio system,
merged by every householding agreement signed by the quarter end; each group's fee is the
schedule's marginal tiers on its quarter-end value of positions plus cash.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from casebook.model.dates import parse_date
from casebook.model.files import (
    CRM_JSON,
    FEE,
    PORTFOLIO_BILLING,
    PORTFOLIO_HOUSEHOLD,
    TRANSACTIONS_COLUMNS,
    TRANSACTIONS_CSV,
    read_cash,
    read_csv,
    read_json,
    read_positions,
)
from casebook.model.money import cents, fmt, parse_decimal

type KeyFinding = Literal["fee_error", "no_fee_error"]

HOUSEHOLDING = "householding"
QUARTERS_PER_YEAR = Decimal(4)
# A difference under a dollar is rounding, not a billing error.
MATERIAL = Decimal("1.00")
ZERO = Decimal(0)


class UnsettledFeeError(ValueError):
    """The household's files cannot settle what the quarter's fee should have been."""


@dataclass(frozen=True)
class Tier:
    up_to: Decimal | None
    annual_rate: Decimal


@dataclass(frozen=True)
class Schedule:
    schedule_id: str
    tiers: tuple[Tier, ...]


@dataclass(frozen=True)
class KeyGroup:
    """Accounts billed together, with the quarter-end value and the quarter's fee."""

    account_ids: tuple[str, ...]
    schedule_id: str
    portfolio_group_ids: tuple[str, ...]
    value: Decimal
    fee: Decimal


@dataclass(frozen=True)
class KeyFigure:
    label: str
    value: Decimal


@dataclass(frozen=True)
class FeeKey:
    household_id: str
    quarter_end: date
    fee_date: date
    finding: KeyFinding
    debited_fee: Decimal
    correct_fee: Decimal
    amount_misbilled: Decimal
    billing_groups: tuple[KeyGroup, ...]
    computed_figures: tuple[KeyFigure, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "household_id": self.household_id,
            "quarter_end": self.quarter_end.isoformat(),
            "fee_date": self.fee_date.isoformat(),
            "finding": self.finding,
            "debited_fee": fmt(self.debited_fee),
            "correct_fee": fmt(self.correct_fee),
            "amount_misbilled": fmt(self.amount_misbilled),
            "billing_groups": [
                {
                    "account_ids": list(g.account_ids),
                    "schedule_id": g.schedule_id,
                    "portfolio_group_ids": list(g.portfolio_group_ids),
                    "value": fmt(g.value),
                    "fee": fmt(g.fee),
                }
                for g in self.billing_groups
            ],
            "computed_figures": [{"label": f.label, "value": fmt(f.value)} for f in self.computed_figures],
        }


@dataclass(frozen=True)
class _Group:
    group_ids: tuple[str, ...]
    schedule_id: str
    account_ids: frozenset[str]

    @property
    def name(self) -> str:
        return " + ".join(sorted(self.account_ids))


def _schedules(root: Path) -> dict[str, Schedule]:
    raw = read_json(root, PORTFOLIO_BILLING)
    return {
        str(s["schedule_id"]): Schedule(
            str(s["schedule_id"]),
            tuple(
                Tier(
                    None if t["up_to"] is None else parse_decimal(str(t["up_to"])), parse_decimal(str(t["annual_rate"]))
                )
                for t in s["tiers"]
            ),
        )
        for s in raw["fee_schedules"]
    }


def _portfolio_groups(root: Path) -> list[_Group]:
    raw = read_json(root, PORTFOLIO_HOUSEHOLD)
    return [
        _Group((str(g["billing_group_id"]),), str(g["schedule_id"]), frozenset(str(a) for a in g["account_ids"]))
        for g in raw["billing_groups"]
    ]


def _merge(groups: list[_Group], agreement: dict[str, Any]) -> list[_Group]:
    accounts = frozenset(str(a) for a in agreement["account_ids"])
    touched = [g for g in groups if g.account_ids & accounts]
    agreement_id = agreement["agreement_id"]
    if not touched:
        raise UnsettledFeeError(f"householding agreement {agreement_id} names no account in any billing group")
    schedules = {g.schedule_id for g in touched}
    if len(schedules) > 1:
        raise UnsettledFeeError(f"householding agreement {agreement_id} joins groups on schedules {sorted(schedules)}")
    merged = _Group(
        tuple(sorted(i for g in touched for i in g.group_ids)),
        touched[0].schedule_id,
        accounts.union(*(g.account_ids for g in touched)),
    )
    return [g for g in groups if g not in touched] + [merged]


def _correct_groups(root: Path, quarter_end: date) -> list[_Group]:
    groups = _portfolio_groups(root)
    agreements = sorted(read_json(root, CRM_JSON)["agreements"], key=lambda a: str(a["signed"]))
    for agreement in agreements:
        if agreement["kind"] == HOUSEHOLDING and parse_date(str(agreement["signed"])) <= quarter_end:
            groups = _merge(groups, agreement)
    return sorted(groups, key=lambda g: g.name)


def _account_values(root: Path, quarter_end: date, account_ids: set[str]) -> dict[str, Decimal]:
    values: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for position in read_positions(root):
        if position.valuation_date == quarter_end:
            values[position.account_id] += position.market_value
    has_cash: set[str] = set()
    for row in read_cash(root):
        if row.valuation_date == quarter_end:
            values[row.account_id] += row.settled_cash + row.unsettled_cash
            has_cash.add(row.account_id)
    missing = sorted(account_ids - has_cash)
    if missing:
        raise UnsettledFeeError(f"accounts {missing} have no cash row on {quarter_end}, so their value is unknown")
    return {a: values[a] for a in sorted(account_ids)}


def _parts(root: Path, account_ids: set[str]) -> list[KeyFigure]:
    """What an answer may add up from the files on any date they cover: each account's positions, cash and value.

    An answer that checks other quarters too works these out; they follow from the files.
    """
    positions: dict[tuple[str, date], Decimal] = defaultdict(lambda: ZERO)
    for position in read_positions(root):
        positions[(position.account_id, position.valuation_date)] += position.market_value
    figures: list[KeyFigure] = []
    for row in read_cash(root):
        if row.account_id in account_ids:
            held = positions[(row.account_id, row.valuation_date)]
            cash = row.settled_cash + row.unsettled_cash
            day = row.valuation_date
            figures += [
                KeyFigure(f"{row.account_id} positions value at {day}", held),
                KeyFigure(f"{row.account_id} cash at {day}", cash),
                KeyFigure(f"{row.account_id} value at {day}", held + cash),
            ]
    return figures


def _tier_portions(value: Decimal, schedule: Schedule) -> list[tuple[Decimal, Decimal]]:
    """The part of the value inside each tier, with that tier's annual rate."""
    portions: list[tuple[Decimal, Decimal]] = []
    lower = ZERO
    for tier in schedule.tiers:
        top = value if tier.up_to is None else min(value, tier.up_to)
        if top > lower:
            portions.append((top - lower, tier.annual_rate))
        if tier.up_to is None or value <= tier.up_to:
            return portions
        lower = tier.up_to
    raise UnsettledFeeError(f"schedule {schedule.schedule_id} has no tier for a value of {fmt(value)}")


def _quarterly_fee(value: Decimal, schedule: Schedule) -> Decimal:
    return cents(sum((part * rate for part, rate in _tier_portions(value, schedule)), ZERO) / QUARTERS_PER_YEAR)


def _group_figures(group: _Group, value: Decimal, schedule: Schedule, kind: str) -> list[KeyFigure]:
    name = f"{kind} group {group.name}"
    figures = [KeyFigure(f"{name} value", value)]
    annual = ZERO
    for part, rate in _tier_portions(value, schedule):
        figures += [
            KeyFigure(f"{name} value at {fmt(rate)}", part),
            KeyFigure(f"{name} annual fee at {fmt(rate)}", part * rate),
            KeyFigure(f"{name} quarterly fee at {fmt(rate)}", part * rate / QUARTERS_PER_YEAR),
        ]
        annual += part * rate
    figures += [
        KeyFigure(f"{name} annual fee", annual),
        KeyFigure(f"{name} quarterly fee", _quarterly_fee(value, schedule)),
    ]
    return figures


def _allocation(
    group: _Group, values: dict[str, Decimal], fee: Decimal, debited: dict[str, Decimal]
) -> list[KeyFigure]:
    """The correct group fee shared across its accounts by value: each share, their sum, each account's overbilling."""
    total = sum((values[a] for a in group.account_ids), ZERO)
    if total == 0:
        return []
    shares = {a: cents(fee * values[a] / total) for a in sorted(group.account_ids)}
    figures = [KeyFigure(f"{a} share of the correct fee", share) for a, share in shares.items()]
    figures.append(KeyFigure(f"correct group {group.name} shares added up", sum(shares.values(), ZERO)))
    figures += [KeyFigure(f"{a} overbilled", debited.get(a, ZERO) - share) for a, share in shares.items()]
    return figures


def _debits(root: Path, quarter_end: date) -> tuple[date, dict[str, Decimal]]:
    rows = [
        r
        for r in read_csv(root, TRANSACTIONS_CSV, TRANSACTIONS_COLUMNS)
        if r["type"] == FEE and quarter_end.isoformat() in r["description"]
    ]
    if not rows:
        raise UnsettledFeeError(f"no {FEE} rows name the quarter to {quarter_end}")
    days = {parse_date(r["trade_date"]) for r in rows}
    if len(days) > 1:
        raise UnsettledFeeError(f"the fees for the quarter to {quarter_end} were debited on {sorted(days)}")
    debited: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for r in rows:
        debited[r["account_id"]] -= parse_decimal(r["amount"])
    return days.pop(), dict(debited)


def fee_key(household_root: Path, quarter_end: date) -> FeeKey:
    household_id = str(read_json(household_root, PORTFOLIO_HOUSEHOLD)["household_id"])
    schedules = _schedules(household_root)
    portfolio = _portfolio_groups(household_root)
    correct = _correct_groups(household_root, quarter_end)
    for group in portfolio:
        if group.schedule_id not in schedules:
            raise UnsettledFeeError(f"billing group {group.group_ids[0]} uses unknown schedule {group.schedule_id}")
    accounts = {a for g in correct for a in g.account_ids}
    values = _account_values(household_root, quarter_end, accounts)
    fee_date, debited = _debits(household_root, quarter_end)

    def group_value(group: _Group) -> Decimal:
        return sum((values[a] for a in group.account_ids), ZERO)

    key_groups = tuple(
        KeyGroup(
            tuple(sorted(g.account_ids)),
            g.schedule_id,
            g.group_ids,
            group_value(g),
            _quarterly_fee(group_value(g), schedules[g.schedule_id]),
        )
        for g in correct
    )
    debited_fee = sum(debited.values(), ZERO)
    correct_fee = sum((g.fee for g in key_groups), ZERO)
    misbilled = debited_fee - correct_fee

    figures = [KeyFigure(f"{a} value at {quarter_end}", v) for a, v in values.items()]
    figures += _parts(household_root, set(values))
    figures += [KeyFigure(f"{a} fee debited", d) for a, d in sorted(debited.items())]
    for g in portfolio:
        figures += _group_figures(g, group_value(g), schedules[g.schedule_id], f"portfolio {g.group_ids[0]}")
        figures.append(
            KeyFigure(
                f"portfolio {g.group_ids[0]} fee debited", sum((debited.get(a, ZERO) for a in g.account_ids), ZERO)
            )
        )
    for g in correct:
        figures += _group_figures(g, group_value(g), schedules[g.schedule_id], "correct")
        figures += _allocation(g, values, _quarterly_fee(group_value(g), schedules[g.schedule_id]), debited)
    figures += [
        KeyFigure("total value", sum(values.values(), ZERO)),
        KeyFigure("fees debited", debited_fee),
        KeyFigure("correct fee", correct_fee),
        KeyFigure("amount misbilled", misbilled),
    ]
    return FeeKey(
        household_id=household_id,
        quarter_end=quarter_end,
        fee_date=fee_date,
        finding="fee_error" if abs(misbilled) >= MATERIAL else "no_fee_error",
        debited_fee=debited_fee,
        correct_fee=correct_fee,
        amount_misbilled=misbilled,
        billing_groups=key_groups,
        computed_figures=tuple(figures),
    )
