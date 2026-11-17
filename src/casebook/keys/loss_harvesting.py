"""The answer key for a compliance review of a household's 2025 loss harvesting across its accounts: are the
losses the custodian reports the losses allowed, and what should a reviewer look at?

The losses are `keys.wash_sales`'s: a 2025 sale at a loss in a taxable account whose units a purchase of the
same security replaced, within the window, in an account of the seller, the seller's spouse or anyone filing
with them, an IRA's included. Each such sale is one issue for the reviewer, named by the sale's transaction
and each replacement purchase's; a household with none has nothing to raise.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from casebook.keys.concentration_basis import ISSUES_FOUND, NO_ISSUES, ReviewFinding
from casebook.keys.issues import Issue
from casebook.keys.wash_sales import WashSaleKey, wash_sale_key


@dataclass(frozen=True)
class LossHarvestingKey:
    wash_sales: WashSaleKey

    @property
    def finding(self) -> ReviewFinding:
        return ISSUES_FOUND if self.wash_sales.washed else NO_ISSUES

    @property
    def issues(self) -> tuple[Issue, ...]:
        """One per sale, though it closed several lots: the sale and every purchase that replaced its units."""
        replaced: dict[str, dict[str, None]] = {}
        for lot in self.wash_sales.washed:
            replaced.setdefault(lot.transaction_id, {}).update(
                dict.fromkeys(r.transaction_id for r in lot.replacements)
            )
        return tuple(
            Issue(f"loss on {sale} replaced within the window", (sale, *buys)) for sale, buys in replaced.items()
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.wash_sales.to_dict(),
            "finding": self.finding,
            "issues": [{"issue": i.name, "records": list(i.records)} for i in self.issues],
        }


def loss_harvesting_key(household_root: Path) -> LossHarvestingKey:
    return LossHarvestingKey(wash_sale_key(household_root))
