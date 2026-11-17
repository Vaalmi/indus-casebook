"""The answer key for T-MTG-06: which households to call before 15 April 2026 about a 2025 tax or
distribution surprise, and why.

Three surprises count, each worked from the files by a key of its own:

- a backdoor Roth taxed pro rata (`keys.backdoor_roth`): a 2025 nondeductible contribution converted to a
  Roth IRA in 2025, of which Form 8606 makes part taxable because the person's other traditional IRAs held
  pre-tax money on 31 December 2025; named with the person and the conversion's transaction;
- a 2025 required minimum distribution not met (`keys.rmd_sweep`); named with the owner and the accounts;
- a 2025 loss sale in a taxable account replaced within 30 days, so some of the loss is a wash sale
  (`keys.wash_sale_sweep`); named with the loss sales and their replacements.

A household is found when any of the three applies to it, and an answer's entry for it names every
identifier each of its surprises carries. Other things that may surprise a client (the net investment
income tax, a mis-coded QCD, a conversion's basis) are not this question's: the prompt names these three.
Shaped for `graders.household_list`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from casebook.keys.backdoor_roth import Backdoor, backdoor_conversions
from casebook.keys.figures import KeyFigure
from casebook.keys.rmd_sweep import RmdSweepKey, rmd_sweep_key
from casebook.keys.wash_sale_sweep import WashSaleSweepKey, wash_sale_sweep_key
from casebook.model.files import household_dir, read_manifest
from casebook.model.money import fmt

BACKDOOR_ROTH_TAXED, RMD_NOT_MET, WASH_SALE = "backdoor_roth_taxed", "rmd_not_met", "wash_sale"
SURPRISES = (BACKDOOR_ROTH_TAXED, RMD_NOT_MET, WASH_SALE)
ZERO = Decimal(0)


@dataclass(frozen=True)
class TaxSurprisesKey:
    checked: tuple[str, ...]
    backdoors: Mapping[str, tuple[Backdoor, ...]]  # each household's taxed backdoor Roths
    rmds: RmdSweepKey
    wash_sales: WashSaleSweepKey
    # Each surprise key settles every household, so none is left unresolved.
    unresolved: tuple[str, ...] = ()

    @property
    def surprises(self) -> Mapping[str, Mapping[str, tuple[str, ...]]]:
        """Each household found, with each of its surprises and the identifiers that surprise carries."""
        by_household: dict[str, dict[str, tuple[str, ...]]] = {}
        for household_id, backdoors in self.backdoors.items():
            ids = [i for b in backdoors for i in (b.person_id, *b.conversion_ids)]
            by_household.setdefault(household_id, {})[BACKDOOR_ROTH_TAXED] = tuple(dict.fromkeys(ids))
        for household_id, ids in self.rmds.found.items():
            by_household.setdefault(household_id, {})[RMD_NOT_MET] = ids
        for household_id, ids in self.wash_sales.found.items():
            by_household.setdefault(household_id, {})[WASH_SALE] = ids
        return {h: by_household[h] for h in sorted(by_household)}

    @property
    def found(self) -> Mapping[str, tuple[str, ...]]:
        return {
            h: tuple(dict.fromkeys(i for ids in surprises.values() for i in ids))
            for h, surprises in self.surprises.items()
        }

    @property
    def computed_figures(self) -> tuple[KeyFigure, ...]:
        backdoor = tuple(
            KeyFigure(f"{h} {f.label}", f.value)
            for h, bs in sorted(self.backdoors.items())
            for b in bs
            for f in b.figures()
        )
        return (*backdoor, *self.rmds.computed_figures, *self.wash_sales.computed_figures)

    @property
    def table_figures(self) -> tuple[Decimal, ...]:
        return self.rmds.table_figures

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": {h: {s: list(ids) for s, ids in surprises.items()} for h, surprises in self.surprises.items()},
            "unresolved": list(self.unresolved),
            "backdoor_roth_taxed": {
                h: [{**b.to_dict(), "taxable_amount": fmt(b.taxable)} for b in bs]
                for h, bs in sorted(self.backdoors.items())
            },
            "rmd_not_met": self.rmds.to_dict()["missed"],
            "wash_sale": self.wash_sales.to_dict()["wash_sales"],
        }


def tax_surprises_key(book: Path) -> TaxSurprisesKey:
    checked = tuple(sorted(h.household_id for h in read_manifest(book).households))
    backdoors: dict[str, tuple[Backdoor, ...]] = {}
    for household_id in checked:
        taxed = tuple(b for b in backdoor_conversions(book / household_dir(household_id)) if b.taxable > ZERO)
        if taxed:
            backdoors[household_id] = taxed
    return TaxSurprisesKey(checked, backdoors, rmd_sweep_key(book), wash_sale_sweep_key(book))
