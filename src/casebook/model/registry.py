"""A registry entry: one planted item (docs/SPEC.md, The book)."""

from dataclasses import dataclass
from typing import Any

PLANTED_KINDS = ("situation", "source_disagreement")


@dataclass(frozen=True)
class FigureTable:
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class RegistryEntry:
    item_id: str
    household_id: str
    kind: str
    item_type: str
    title: str
    sources: tuple[str, ...]
    conclusion: str
    figures: tuple[tuple[str, str], ...]
    table: FigureTable

    def __post_init__(self) -> None:
        if self.kind not in PLANTED_KINDS:
            raise ValueError(f"planted item {self.item_id}: kind {self.kind!r} is not one of {PLANTED_KINDS}")
        if not self.sources:
            raise ValueError(f"planted item {self.item_id} names no sources")

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "household_id": self.household_id,
            "kind": self.kind,
            "type": self.item_type,
            "title": self.title,
            "sources": list(self.sources),
            "justified_conclusion": self.conclusion,
            "figures": [{"label": label, "value": value} for label, value in self.figures],
            "table": {"columns": list(self.table.columns), "rows": [list(r) for r in self.table.rows]},
        }


def parse_entry(raw: dict[str, Any]) -> RegistryEntry:
    table = raw["table"]
    return RegistryEntry(
        item_id=str(raw["item_id"]),
        household_id=str(raw["household_id"]),
        kind=str(raw["kind"]),
        item_type=str(raw["type"]),
        title=str(raw["title"]),
        sources=tuple(str(s) for s in raw["sources"]),
        conclusion=str(raw["justified_conclusion"]),
        figures=tuple((str(f["label"]), str(f["value"])) for f in raw["figures"]),
        table=FigureTable(
            columns=tuple(str(c) for c in table["columns"]),
            rows=tuple(tuple(str(v) for v in row) for row in table["rows"]),
        ),
    )
