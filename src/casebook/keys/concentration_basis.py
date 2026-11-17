"""The answer key for a compliance review of a household against its IPS and its cost basis: is a single
company's stock above the IPS concentration limit on the review date, and can the custodian's cost basis for
shares released from restricted stock units be relied on?

Concentration is `keys.ips_review`'s. Basis: each release confirmation in the CRM gives the account, the
security, the release date, the units and the price; the release value is wages, so it is the shares' basis
(Treas. Reg. § 1.83-4(b)(1)), units times price to the cent. A custodian lot of that security in that account
acquired on the release date, held on the review date or sold in the tax year, should carry that basis per
share. The key totals what the lots still held understate, and by how much the realized lots overstate the
year's gains.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from casebook.keys.figures import KeyFigure
from casebook.keys.ips_review import IpsReview, ips_review
from casebook.keys.issues import Issue
from casebook.model.dates import parse_date
from casebook.model.files import CRM_JSON, RSU_RELEASE, read_json, read_realized, read_tax_lots
from casebook.model.money import cents, fmt, parse_decimal

type ReviewFinding = Literal["issues_found", "no_issues"]
ISSUES_FOUND: ReviewFinding = "issues_found"
NO_ISSUES: ReviewFinding = "no_issues"
ZERO = Decimal(0)


class UnsettledBasisError(ValueError):
    """The household's files cannot settle the basis review."""


@dataclass(frozen=True)
class Release:
    activity_id: str
    account_id: str
    security_id: str
    released: date
    units: Decimal
    price: Decimal


@dataclass(frozen=True)
class LotBasis:
    """A lot from a release: the basis the custodian shows, and what the release confirmation supports."""

    lot_id: str
    activity_id: str
    units: Decimal
    shown: Decimal
    supported: Decimal
    # The realized lot's sale, or None for a lot still held.
    transaction_id: str | None = None

    @property
    def understated(self) -> Decimal:
        return self.supported - self.shown


@dataclass(frozen=True)
class ConcentrationBasisKey:
    household_id: str
    as_of: date
    tax_year: int
    finding: ReviewFinding
    ips: IpsReview
    held: tuple[LotBasis, ...]
    sold: tuple[LotBasis, ...]
    computed_figures: tuple[KeyFigure, ...]

    @property
    def basis_reliable(self) -> bool:
        return all(lot.understated == ZERO for lot in (*self.held, *self.sold))

    @property
    def basis_understated(self) -> Decimal:
        return sum((lot.understated for lot in self.held), ZERO)

    @property
    def gain_overstated(self) -> Decimal:
        return sum((lot.understated for lot in self.sold), ZERO)

    @property
    def above_limit(self) -> dict[str, Decimal]:
        return {c.security_id: c.value for c in self.ips.concentrations}

    @property
    def issues(self) -> tuple[Issue, ...]:
        """One issue per stock above the limit, one for the lots held and one for the lots sold with the wrong basis."""
        found = [
            Issue(f"{c.security_id} above the concentration limit", (c.security_id,)) for c in self.ips.concentrations
        ]
        wrong_held = tuple(lot.lot_id for lot in self.held if lot.understated)
        wrong_sold = tuple(dict.fromkeys(lot.lot_id for lot in self.sold if lot.understated))
        if wrong_held:
            found.append(Issue("basis wrong on released shares still held", wrong_held))
        if wrong_sold:
            found.append(Issue(f"basis wrong on released shares sold in {self.tax_year}", wrong_sold))
        return tuple(found)

    def to_dict(self) -> dict[str, Any]:
        def lot(item: LotBasis) -> dict[str, Any]:
            return {
                "lot_id": item.lot_id,
                "activity_id": item.activity_id,
                "transaction_id": item.transaction_id,
                "units": fmt(item.units),
                "basis_shown": fmt(item.shown),
                "basis_supported": fmt(item.supported),
            }

        return {
            "household_id": self.household_id,
            "as_of": self.as_of.isoformat(),
            "tax_year": self.tax_year,
            "finding": self.finding,
            **self.ips.to_dict(),
            "basis_reliable": self.basis_reliable,
            "basis_understated": fmt(self.basis_understated),
            "gain_overstated": fmt(self.gain_overstated),
            "lots_held": [lot(x) for x in self.held],
            "lots_sold": [lot(x) for x in self.sold],
            "issues": [{"issue": i.name, "records": list(i.records)} for i in self.issues],
            "computed_figures": [{"label": f.label, "value": fmt(f.value)} for f in self.computed_figures],
        }


def _releases(root: Path) -> list[Release]:
    return [
        Release(
            str(a["activity_id"]),
            str(a["account_id"]),
            str(a["security_id"]),
            parse_date(str(a["refers_to"])),
            parse_decimal(str(a["units"])),
            parse_decimal(str(a["price"])),
        )
        for a in read_json(root, CRM_JSON)["activities"]
        if a["kind"] == RSU_RELEASE
    ]


def _release_of(releases: list[Release], account_id: str, security_id: str, acquired: date) -> Release | None:
    matches = [r for r in releases if (r.account_id, r.security_id, r.released) == (account_id, security_id, acquired)]
    if len(matches) > 1:
        raise UnsettledBasisError(f"{len(matches)} release confirmations for {security_id} on {acquired}")
    return matches[0] if matches else None


def _lot_figures(kind: str, lots: tuple[LotBasis, ...]) -> list[KeyFigure]:
    figures: list[KeyFigure] = []
    for lot in lots:
        figures += [
            KeyFigure(f"{kind} {lot.lot_id} basis supported", lot.supported),
            KeyFigure(f"{kind} {lot.lot_id} basis understated", lot.understated),
        ]
    figures += [
        KeyFigure(f"{kind} basis shown", sum((lot.shown for lot in lots), ZERO)),
        KeyFigure(f"{kind} basis supported", sum((lot.supported for lot in lots), ZERO)),
        KeyFigure(f"{kind} basis understated", sum((lot.understated for lot in lots), ZERO)),
    ]
    return figures


def concentration_basis_key(household_root: Path, as_of: date, tax_year: int) -> ConcentrationBasisKey:
    ips = ips_review(household_root, as_of)
    releases = _releases(household_root)
    held: list[LotBasis] = []
    lots_on_day = [lot for lot in read_tax_lots(household_root) if lot.valuation_date == as_of]
    if not lots_on_day:
        raise UnsettledBasisError(f"{ips.household_id} has no tax lots on {as_of}")
    for lot in lots_on_day:
        release = _release_of(releases, lot.account_id, lot.security_id, lot.acquired_date)
        if release is not None:
            held.append(
                LotBasis(lot.lot_id, release.activity_id, lot.units, lot.cost_basis, cents(lot.units * release.price))
            )
    sold: list[LotBasis] = []
    gains: list[KeyFigure] = []
    for row in read_realized(household_root):
        release = _release_of(releases, row.account_id, row.security_id, row.acquired_date)
        if release is None or row.sold_date.year != tax_year:
            continue
        supported = cents(row.units * release.price)
        sold.append(LotBasis(row.lot_id, release.activity_id, row.units, row.cost_basis, supported, row.transaction_id))
        gains.append(KeyFigure(f"sold {row.lot_id} true gain", row.proceeds - supported))
    held_lots, sold_lots = tuple(held), tuple(sold)
    figures = [
        *ips.computed_figures,
        *(KeyFigure(f"{r.activity_id} release value", cents(r.units * r.price)) for r in releases),
        KeyFigure("release value, every confirmation", sum((cents(r.units * r.price) for r in releases), ZERO)),
        *_lot_figures("held", held_lots),
        *_lot_figures("sold", sold_lots),
        *gains,
        KeyFigure(f"{tax_year} true gain on released shares sold", sum((g.value for g in gains), ZERO)),
    ]
    wrong = any(lot.understated for lot in (*held_lots, *sold_lots))
    return ConcentrationBasisKey(
        household_id=ips.household_id,
        as_of=as_of,
        tax_year=tax_year,
        finding=ISSUES_FOUND if ips.concentrations or wrong else NO_ISSUES,
        ips=ips,
        held=held_lots,
        sold=sold_lots,
        computed_figures=tuple(figures),
    )
