"""Portfolio-system JSON: the household and its five relations, the fee schedule, the IPS, trade-date positions."""

from typing import Any

from casebook.model.dates import PRIOR_YEAR_END, SCENARIO_DATE
from casebook.model.files import (
    PORTFOLIO_BILLING,
    PORTFOLIO_HOUSEHOLD,
    PORTFOLIO_IPS,
    PORTFOLIO_POSITIONS,
    PORTFOLIO_TAX_PROFILE,
    SYNTHETIC,
    json_text,
)
from casebook.model.money import cents, fmt
from casebook.sources.context import EmitContext

TODAY = {"valuation_date": SCENARIO_DATE.isoformat(), "known_as_of": SCENARIO_DATE.isoformat()}


def _household(context: EmitContext) -> dict[str, Any]:
    hh = context.script.household
    changed = {"last_changed": hh.configured.isoformat(), **TODAY}
    return {
        "household_id": hh.household_id,
        "name": hh.name,
        "household_membership": [
            {
                "person_id": p.person_id,
                "name": p.name,
                "born": p.born.isoformat(),
                "relationship": p.relationship,
                **TODAY,
            }
            for p in hh.members
        ],
        "legal_ownership": [
            {"account_id": o.account_id, "owner_ids": list(o.owner_ids), **TODAY} for o in hh.ownership
        ],
        "tax_units": [
            {"tax_unit_id": t.tax_unit_id, "filing_status": t.filing_status, "person_ids": list(t.person_ids), **TODAY}
            for t in hh.tax_units
        ],
        "billing_groups": [
            {
                "billing_group_id": g.billing_group_id,
                "schedule_id": g.schedule_id,
                "account_ids": list(g.account_ids),
                **changed,
            }
            for g in hh.billing_groups
        ],
        "disclosure_permissions": [
            {"person_id": d.person_id, "may_be_told_about": list(d.account_ids), **TODAY} for d in hh.disclosures
        ],
    }


def _billing(context: EmitContext) -> dict[str, Any]:
    schedule = context.script.household.fee_schedule
    return {
        "fee_schedules": [
            {
                "schedule_id": schedule.schedule_id,
                "basis": schedule.basis,
                "tiers": [
                    {"up_to": fmt(t.up_to) if t.up_to is not None else None, "annual_rate": fmt(t.annual_rate)}
                    for t in schedule.tiers
                ],
                **TODAY,
            }
        ]
    }


def _ips(context: EmitContext) -> dict[str, Any]:
    hh = context.script.household
    return {
        "targets": [
            {"asset_class": t.asset_class, "target": fmt(t.target), "band": fmt(t.band), **TODAY} for t in hh.allocation
        ],
        "asset_classes": [
            {"security_id": sid, "security": context.label(sid), "asset_class": cls, **TODAY}
            for sid, cls in sorted(hh.asset_classes.items())
        ],
        "restrictions": [
            {
                "restriction_id": r.restriction_id,
                "restriction": r.text,
                "valuation_date": r.recorded.isoformat(),
                "known_as_of": r.recorded.isoformat(),
            }
            for r in hh.restrictions
        ],
        "concentration_limit": {"share_of_household": fmt(hh.concentration_limit), **TODAY},
    }


def _tax_profile(context: EmitContext) -> dict[str, Any]:
    """What the advisor's planning system carries in from the 2024 return."""
    profile = context.script.household.tax_profile
    dates = {"valuation_date": PRIOR_YEAR_END.isoformat(), "known_as_of": profile.known_as_of.isoformat()}
    return {
        "loss_carryforwards": [
            {"tax_unit_id": c.tax_unit_id, "short_term": fmt(c.short_term), "long_term": fmt(c.long_term), **dates}
            for c in profile.loss_carryforwards
        ],
        "ira_basis": [{"person_id": b.person_id, "basis": fmt(b.basis), **dates} for b in profile.ira_basis],
    }


def _positions(context: EmitContext) -> dict[str, Any]:
    final = context.replayed.snapshots[SCENARIO_DATE]
    positions: list[dict[str, Any]] = []
    cash: list[dict[str, Any]] = []
    for account in context.script.household.accounts:
        for sid, units in final.holdings(account.account_id).items():
            price = context.market.price(sid, SCENARIO_DATE)
            positions.append(
                {
                    "account_id": account.account_id,
                    "security_id": sid,
                    "security": context.label(sid),
                    "units": fmt(units),
                    "price": fmt(price),
                    "price_label": SYNTHETIC,
                    "market_value": fmt(cents(units * price)),
                    "basis": "trade date",
                    **TODAY,
                }
            )
        total = final.settled_cash[account.account_id] + final.unsettled_cash[account.account_id]
        cash.append({"account_id": account.account_id, "cash": fmt(cents(total)), "basis": "trade date", **TODAY})
    return {"positions": positions, "cash": cash}


def emit(context: EmitContext) -> dict[str, bytes]:
    return {
        PORTFOLIO_HOUSEHOLD: json_text(_household(context)).encode(),
        PORTFOLIO_BILLING: json_text(_billing(context)).encode(),
        PORTFOLIO_IPS: json_text(_ips(context)).encode(),
        PORTFOLIO_POSITIONS: json_text(_positions(context)).encode(),
        PORTFOLIO_TAX_PROFILE: json_text(_tax_profile(context)).encode(),
    }
