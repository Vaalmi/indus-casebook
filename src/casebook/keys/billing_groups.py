"""The answer key for T-REC-05: which households are billed in groups that a signed householding agreement
contradicts.

For each household of the book it reads the portfolio system's billing groups (portfolio/household.json) and
the CRM's agreements (crm/crm.json), as known on the as-of date. A householding agreement signed by then joins
its accounts in one billing group; the household is found when no billing group holds all of them. Its
evidence is the agreement and the billing groups that hold its accounts apart.

The figures are the fee key's, for every quarter billed by the as-of date, on each household an answer might
price: one the key finds, and every look-alike billed in more than one group. Their totals across the
quarters are the overbilling an answer may work out since the agreement.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from casebook.keys.fee_reconciliation import FeeKey, UnsettledFeeError, fee_key
from casebook.keys.figures import KeyFigure
from casebook.model.dates import QUARTER_ENDS, parse_date
from casebook.model.files import CRM_JSON, PORTFOLIO_HOUSEHOLD, household_dir, read_json, read_manifest
from casebook.model.money import fmt

HOUSEHOLDING = "householding"
KNOWN = "known_as_of"
ZERO = Decimal(0)


@dataclass(frozen=True)
class Contradiction:
    """A signed householding agreement whose accounts the billing groups hold apart."""

    household_id: str
    agreement_id: str
    signed: date
    account_ids: tuple[str, ...]
    billing_group_ids: tuple[str, ...]


@dataclass(frozen=True)
class HouseholdFigures:
    household_id: str
    figures: tuple[KeyFigure, ...]


@dataclass(frozen=True)
class BillingGroupsKey:
    as_of: date
    checked: tuple[str, ...]
    contradictions: tuple[Contradiction, ...]
    household_figures: tuple[HouseholdFigures, ...]
    # Every agreement names the accounts it joins, so the files settle each household.
    unresolved: tuple[str, ...] = ()

    @property
    def found(self) -> Mapping[str, tuple[str, ...]]:
        evidence: dict[str, list[str]] = {}
        for c in self.contradictions:
            evidence.setdefault(c.household_id, []).extend([c.agreement_id, *c.billing_group_ids])
        return {h: tuple(dict.fromkeys(ids)) for h, ids in sorted(evidence.items())}

    @property
    def computed_figures(self) -> tuple[KeyFigure, ...]:
        return tuple(f for h in self.household_figures for f in h.figures)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "checked": list(self.checked),
            "found": {h: list(ids) for h, ids in self.found.items()},
            "unresolved": list(self.unresolved),
            "contradictions": [
                {
                    "household_id": c.household_id,
                    "agreement_id": c.agreement_id,
                    "signed": c.signed.isoformat(),
                    "account_ids": list(c.account_ids),
                    "billing_group_ids": list(c.billing_group_ids),
                }
                for c in self.contradictions
            ],
            "computed_figures": {
                h.household_id: [{"label": f.label, "value": fmt(f.value)} for f in h.figures]
                for h in self.household_figures
            },
        }


def _known(items: list[dict[str, Any]], as_of: date) -> list[dict[str, Any]]:
    return [i for i in items if KNOWN not in i or parse_date(str(i[KNOWN])) <= as_of]


def _contradictions(root: Path, household_id: str, as_of: date) -> list[Contradiction]:
    groups = [
        (str(g["billing_group_id"]), frozenset(str(a) for a in g["account_ids"]))
        for g in _known(read_json(root, PORTFOLIO_HOUSEHOLD)["billing_groups"], as_of)
    ]
    found: list[Contradiction] = []
    for agreement in _known(read_json(root, CRM_JSON)["agreements"], as_of):
        signed = parse_date(str(agreement["signed"]))
        if agreement["kind"] != HOUSEHOLDING or signed > as_of:
            continue
        joined = frozenset(str(a) for a in agreement["account_ids"])
        if any(joined <= accounts for _, accounts in groups):
            continue
        found.append(
            Contradiction(
                household_id=household_id,
                agreement_id=str(agreement["agreement_id"]),
                signed=signed,
                account_ids=tuple(sorted(joined)),
                billing_group_ids=tuple(sorted(g for g, accounts in groups if accounts & joined)),
            )
        )
    return found


def _priced(root: Path) -> bool:
    """A household an answer might price: billed in more than one group, or under a householding agreement."""
    groups = read_json(root, PORTFOLIO_HOUSEHOLD)["billing_groups"]
    return len(groups) > 1 or any(a["kind"] == HOUSEHOLDING for a in read_json(root, CRM_JSON)["agreements"])


def _fee_figures(root: Path, as_of: date) -> tuple[KeyFigure, ...]:
    keys: list[FeeKey] = []
    for quarter_end in QUARTER_ENDS:
        if quarter_end > as_of:
            continue
        try:
            keys.append(fee_key(root, quarter_end))
        except UnsettledFeeError:
            continue
    figures = [KeyFigure(f"quarter to {k.quarter_end}: {f.label}", f.value) for k in keys for f in k.computed_figures]
    misbilled = [k for k in keys if k.finding == "fee_error"]
    for label, chosen in (("every quarter", keys), ("quarters misbilled", misbilled)):
        figures += [
            KeyFigure(f"fees debited, {label}", sum((k.debited_fee for k in chosen), ZERO)),
            KeyFigure(f"correct fees, {label}", sum((k.correct_fee for k in chosen), ZERO)),
            KeyFigure(f"amount misbilled, {label}", sum((k.amount_misbilled for k in chosen), ZERO)),
        ]
    return tuple(figures)


def billing_groups_key(book: Path, as_of: date) -> BillingGroupsKey:
    checked = tuple(sorted(h.household_id for h in read_manifest(book).households))
    contradictions: list[Contradiction] = []
    household_figures: list[HouseholdFigures] = []
    for household_id in checked:
        root = book / household_dir(household_id)
        found = _contradictions(root, household_id, as_of)
        contradictions += found
        if found or _priced(root):
            household_figures.append(HouseholdFigures(household_id, _fee_figures(root, as_of)))
    return BillingGroupsKey(as_of, checked, tuple(contradictions), tuple(household_figures))
