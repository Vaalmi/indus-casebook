"""The answer key for an IPS review on one day: which single company's stock is above the household's
concentration limit, and which asset class sits outside its band.

Values are the custodian's positions on the day; a share is of the household's whole value, positions plus
cash, as the IPS's weights are. The concentration limit is on a single company's stock: a fund is not a
concentration. The book's funds carry "Fund" in their names (`model.tax.FUND`); the key reads the name from
the security master by security ID, so the real-ticker build, whose files name tickers, gives the same answer.
An asset class drifts when its holdings, classed as the IPS classes each security, are more than its band
from its target.

An IPS exception would be a record in the CRM, and the book's CRM holds none: a household whose CRM has any
record of an exception is refused rather than read as having none.
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from casebook.keys.figures import KeyFigure
from casebook.model.files import (
    CRM_JSON,
    PORTFOLIO_HOUSEHOLD,
    PORTFOLIO_IPS,
    household_dir,
    read_cash,
    read_json,
    read_manifest,
    read_positions,
)
from casebook.model.money import cents, fmt, parse_decimal
from casebook.model.tax import FUND
from casebook.securities.master import by_id, load_master

ZERO = Decimal(0)
HUNDRED = Decimal(100)
EXCEPTION = "exception"


class UnsettledIpsError(ValueError):
    """The household's files cannot settle the review."""


def percent(share: Decimal) -> Decimal:
    """A share as a percentage, to the hundredth: 0.32490 is 32.49."""
    return cents(share * HUNDRED)


@dataclass(frozen=True)
class Concentration:
    """A single company's stock above the limit."""

    security_id: str
    value: Decimal
    share: Decimal
    limit: Decimal


@dataclass(frozen=True)
class Drift:
    """An asset class outside its band."""

    asset_class: str
    value: Decimal
    share: Decimal
    target: Decimal
    band: Decimal


@dataclass(frozen=True)
class IpsReview:
    household_id: str
    as_of: date
    total: Decimal
    concentrations: tuple[Concentration, ...]
    drifts: tuple[Drift, ...]
    computed_figures: tuple[KeyFigure, ...]

    @property
    def crosses(self) -> bool:
        return bool(self.concentrations or self.drifts)

    @property
    def evidence(self) -> tuple[str, ...]:
        """What an answer names for this household: each stock above the limit, then each class outside its band."""
        return (*(c.security_id for c in self.concentrations), *(d.asset_class for d in self.drifts))

    def to_dict(self) -> dict[str, Any]:
        return {
            "household_id": self.household_id,
            "as_of": self.as_of.isoformat(),
            "total": fmt(self.total),
            "above_concentration_limit": [
                {
                    "security_id": c.security_id,
                    "value": fmt(c.value),
                    "share_percent": fmt(percent(c.share)),
                    "limit_percent": fmt(percent(c.limit)),
                }
                for c in self.concentrations
            ],
            "outside_band": [
                {
                    "asset_class": d.asset_class,
                    "value": fmt(d.value),
                    "share_percent": fmt(percent(d.share)),
                    "target_percent": fmt(percent(d.target)),
                    "band_percent": fmt(percent(d.band)),
                }
                for d in self.drifts
            ],
        }


def single_stocks() -> frozenset[str]:
    """The security IDs of every single company's stock in the security master."""
    return frozenset(s.internal_id for s in by_id(load_master()).values() if FUND not in s.alias)


def _refuse_exceptions(root: Path) -> None:
    crm = read_json(root, CRM_JSON)
    records = [*crm.get("agreements", []), *crm.get("activities", [])]
    noted = [str(r.get("agreement_id") or r.get("activity_id")) for r in records if EXCEPTION in str(r["kind"])]
    if noted:
        raise UnsettledIpsError(f"the CRM records an exception ({', '.join(noted)}), which this key does not read")


def ips_review(household_root: Path, as_of: date) -> IpsReview:
    _refuse_exceptions(household_root)
    household_id = str(read_json(household_root, PORTFOLIO_HOUSEHOLD)["household_id"])
    ips = read_json(household_root, PORTFOLIO_IPS)
    classes = {str(c["security_id"]): str(c["asset_class"]) for c in ips["asset_classes"]}
    by_security: dict[str, Decimal] = defaultdict(lambda: ZERO)
    by_account: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for row in read_positions(household_root):
        if row.valuation_date == as_of:
            by_security[row.security_id] += row.market_value
            by_account[row.account_id] += row.market_value
    cash_rows = [c for c in read_cash(household_root) if c.valuation_date == as_of]
    if not cash_rows:
        raise UnsettledIpsError(f"{household_id} has no cash on {as_of}, so its value is unknown")
    cash = sum((c.settled_cash + c.unsettled_cash for c in cash_rows), ZERO)
    total = sum(by_security.values(), ZERO) + cash
    unclassed = sorted(set(by_security) - set(classes))
    if unclassed:
        raise UnsettledIpsError(f"{household_id}: the IPS classes no asset class for {', '.join(unclassed)}")

    stocks = single_stocks()
    limit = parse_decimal(str(ips["concentration_limit"]["share_of_household"]))
    concentrations = tuple(
        Concentration(s, v, v / total, limit)
        for s, v in sorted(by_security.items())
        if s in stocks and v / total > limit
    )
    by_class: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for security, value in by_security.items():
        by_class[classes[security]] += value
    drifts: list[Drift] = []
    figures = [
        KeyFigure("household value", total),
        KeyFigure("household cash", cash),
        KeyFigure("household positions", total - cash),
        KeyFigure("concentration limit, percent", percent(limit)),
    ]
    for target in ips["targets"]:
        name = str(target["asset_class"])
        aim, band = parse_decimal(str(target["target"])), parse_decimal(str(target["band"]))
        share = by_class[name] / total
        if abs(share - aim) > band:
            drifts.append(Drift(name, by_class[name], share, aim, band))
        figures += [
            KeyFigure(f"{name} value", by_class[name]),
            KeyFigure(f"{name} share, percent", percent(share)),
            KeyFigure(f"{name} band low, percent", percent(aim - band)),
            KeyFigure(f"{name} band high, percent", percent(aim + band)),
            KeyFigure(f"{name} distance from target, percent", percent(abs(share - aim))),
        ]
    for security, value in sorted(by_security.items()):
        figures += [
            KeyFigure(f"{security} value", value),
            KeyFigure(f"{security} share, percent", percent(value / total)),
            KeyFigure(f"{security} above the limit", value - cents(limit * total)),
        ]
    for account, value in sorted(by_account.items()):
        held_cash = sum((c.settled_cash + c.unsettled_cash for c in cash_rows if c.account_id == account), ZERO)
        figures += [
            KeyFigure(f"{account} positions", value),
            KeyFigure(f"{account} value", value + held_cash),
        ]
    figures.append(KeyFigure("concentration limit in dollars", cents(limit * total)))
    return IpsReview(household_id, as_of, total, concentrations, tuple(drifts), tuple(figures))


@dataclass(frozen=True)
class IpsSweepKey:
    """The book-level key: every household above a concentration limit or outside a band, with no exception."""

    checked: tuple[str, ...]
    reviews: Mapping[str, IpsReview]
    # The IPS and the positions settle every household.
    unresolved: tuple[str, ...] = ()

    @property
    def found(self) -> Mapping[str, tuple[str, ...]]:
        return {h: r.evidence for h, r in sorted(self.reviews.items()) if r.crosses}

    @property
    def computed_figures(self) -> tuple[KeyFigure, ...]:
        return tuple(KeyFigure(f"{h} {f.label}", f.value) for h, r in self.reviews.items() for f in r.computed_figures)

    def to_dict(self) -> dict[str, Any]:
        found = self.found
        return {
            "checked": list(self.checked),
            "found": {h: list(ids) for h, ids in found.items()},
            "unresolved": list(self.unresolved),
            "cleared": sorted(set(self.checked) - set(found) - set(self.unresolved)),
            "reviews": {h: self.reviews[h].to_dict() for h in found},
        }


def ips_sweep_key(book: Path, as_of: date) -> IpsSweepKey:
    checked = tuple(h.household_id for h in read_manifest(book).households)
    return IpsSweepKey(checked, {h: ips_review(book / household_dir(h), as_of) for h in checked})
