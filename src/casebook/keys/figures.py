"""What every key shares: a figure the key computes, which an answer may cite (the fabricated-figure rule
accepts it within a dollar)."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class KeyFigure:
    label: str
    value: Decimal
