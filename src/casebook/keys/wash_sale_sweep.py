"""The answer key for the book-level wash-sale sweep: which households sold at a loss in 2025 and replaced
the shares within 30 days in an account of the seller, the seller's spouse or anyone filing with them.

Each household is the wash-sale review's key (`keys.wash_sales`) on its own files. The answer is a list
of households, graded by `graders.household_list`: the key finds every household with a disallowed loss,
each to be named with its loss sale's and its replacements' transaction IDs, and clears every other
household in the book. The files settle every household, so none is left unresolved.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from casebook.keys.figures import KeyFigure
from casebook.keys.wash_sales import ZERO, WashSaleKey, wash_sale_key
from casebook.model.files import household_dir, read_manifest
from casebook.model.money import fmt


@dataclass(frozen=True)
class WashSaleSweepKey:
    # Every household in the book.
    checked: tuple[str, ...]
    # The expected set: each household with a wash sale, with the sale and replacement transactions to name.
    found: Mapping[str, tuple[str, ...]]
    unresolved: tuple[str, ...]
    # Each found household's own figures: the loss reported, the part disallowed, the part allowed.
    figures: Mapping[str, tuple[KeyFigure, ...]]
    reviews: Mapping[str, WashSaleKey]
    # Every figure any household's review invites an answer to derive, labelled with its household.
    computed_figures: tuple[KeyFigure, ...]

    def to_dict(self) -> dict[str, Any]:
        found = sorted(self.found)
        return {
            "found": {h: list(self.found[h]) for h in found},
            "unresolved": list(self.unresolved),
            "cleared": sorted(set(self.checked) - set(self.found) - set(self.unresolved)),
            "figures": {h: [{"label": f.label, "value": fmt(f.value)} for f in self.figures[h]] for h in found},
            "wash_sales": {h: [lot.to_dict() for lot in self.reviews[h].washed] for h in found},
            "computed_figures": [{"label": f.label, "value": fmt(f.value)} for f in self.computed_figures],
        }


def _evidence(review: WashSaleKey) -> tuple[str, ...]:
    """The loss sales a replacement washes, then their replacements, each named once."""
    sales = [lot.transaction_id for lot in review.washed]
    replacements = [r.transaction_id for lot in review.washed for r in lot.replacements]
    return tuple(dict.fromkeys(sales + replacements))


def wash_sale_sweep_key(book: Path) -> WashSaleSweepKey:
    checked = tuple(h.household_id for h in read_manifest(book).households)
    reviews = {h: wash_sale_key(book / household_dir(h)) for h in checked}
    found = sorted(h for h, review in reviews.items() if review.finding == "wash_sale")
    figures = {
        h: (
            KeyFigure("loss reported", reviews[h].loss_reported),
            KeyFigure("disallowed loss", reviews[h].disallowed_loss),
            KeyFigure("allowed loss", reviews[h].allowed_loss),
        )
        for h in found
    }
    computed = tuple(KeyFigure(f"{h} {f.label}", f.value) for h in checked for f in reviews[h].computed_figures)
    disallowed = sum((reviews[h].disallowed_loss for h in found), ZERO)
    return WashSaleSweepKey(
        checked=checked,
        found={h: _evidence(reviews[h]) for h in found},
        unresolved=(),
        figures=figures,
        reviews={h: reviews[h] for h in found},
        computed_figures=(*computed, KeyFigure("book disallowed loss", disallowed)),
    )
