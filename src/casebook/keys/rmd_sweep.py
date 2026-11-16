"""The answer key for T-TAX-05: which IRA owners in the book had a 2025 required minimum distribution that
was not met.

Each household's RMDs are `keys.rmd`'s: its traditional IRAs together per owner, each 401(k) and each
inherited IRA on its own, each by its deadline (1 April 2026 in a first distribution year, otherwise 31
December 2025). A household is found when any of them was short; its evidence is the owner and the
accounts whose RMD was short. Shaped for `graders.household_list`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from casebook.keys.figures import KeyFigure
from casebook.keys.rmd import YEAR, HouseholdRmd, Requirement, household_rmd
from casebook.model.files import household_dir, read_manifest
from casebook.model.money import fmt
from casebook.rules import load_rules


@dataclass(frozen=True)
class RmdSweepKey:
    checked: tuple[str, ...]
    households: tuple[HouseholdRmd, ...]
    # Every RMD rests on balances, dates and payouts the files give, so the files settle each household.
    unresolved: tuple[str, ...] = ()

    @property
    def missed(self) -> tuple[tuple[str, Requirement], ...]:
        return tuple((h.household_id, r) for h in self.households for r in h.missed)

    @property
    def found(self) -> Mapping[str, tuple[str, ...]]:
        """Each household with an RMD not met, with the owner and the accounts an answer must name."""
        evidence: dict[str, list[str]] = {}
        for household_id, r in self.missed:
            evidence.setdefault(household_id, []).extend([r.owner_id, *r.account_ids])
        return {h: tuple(dict.fromkeys(ids)) for h, ids in sorted(evidence.items())}

    @property
    def computed_figures(self) -> tuple[KeyFigure, ...]:
        return tuple(f for h in self.households for f in h.computed_figures)

    @property
    def table_figures(self) -> tuple[Decimal, ...]:
        return tuple(sorted({v for h in self.households for v in h.table_figures}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked": list(self.checked),
            "found": {h: list(ids) for h, ids in self.found.items()},
            "unresolved": list(self.unresolved),
            "missed": [
                {
                    "household_id": household_id,
                    "owner_id": r.owner_id,
                    "account_type": r.account_type,
                    "account_ids": list(r.account_ids),
                    "rmd": fmt(r.rmd),
                    "deadline": r.deadline.isoformat(),
                    "taken": fmt(r.taken),
                    "shortfall": fmt(r.shortfall),
                }
                for household_id, r in self.missed
            ],
            "households": {h.household_id: h.to_dict() for h in self.households if h.requirements},
        }


def rmd_sweep_key(book: Path) -> RmdSweepKey:
    rules = load_rules(YEAR)
    checked = tuple(sorted(h.household_id for h in read_manifest(book).households))
    households = tuple(household_rmd(book / household_dir(h), rules) for h in checked)
    return RmdSweepKey(checked, households)
