"""The cited real 2025 trading ranges of the securities two tasks turn on (`real_ranges.toml`)."""

import tomllib
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from pathlib import Path

RANGES = Path(__file__).with_name("real_ranges.toml")
# docs/PLAN.md, Choices: "differs sharply" is at least three times a real range's high or at most a third of its low.
SHARPLY = Decimal(3)


@dataclass(frozen=True)
class CitedRange:
    task_id: str
    household_id: str
    security_id: str
    low: Decimal
    high: Decimal
    source: str

    def differs_sharply(self, price: Decimal) -> bool:
        return price >= self.high * SHARPLY or price * SHARPLY <= self.low


@cache
def real_ranges() -> dict[str, CitedRange]:
    """Each cited range by the household its task is on."""
    with RANGES.open("rb") as handle:
        raw = tomllib.load(handle)
    return {
        str(r["household_id"]): CitedRange(
            task_id=str(r["task_id"]),
            household_id=str(r["household_id"]),
            security_id=str(r["security_id"]),
            low=Decimal(str(r["low"])),
            high=Decimal(str(r["high"])),
            source=str(r["source"]),
        )
        for r in raw["ranges"]
    }
