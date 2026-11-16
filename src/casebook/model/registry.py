"""A registry entry: one planted item (docs/SPEC.md, The book)."""

from dataclasses import dataclass
from datetime import date
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
    # The first day the conclusion can be reached from the files: the day its last piece of evidence
    # is on record. A note citing the item cannot be dated earlier (docs/SPEC.md, No future evidence).
    known_as_of: date
    # The records the item is about (transaction, account, agreement, security IDs): a check
    # accepts an entry only for the very records it names.
    references: tuple[str, ...] = ()
    # The thresholds the situation crosses by design (a concentration above the IPS limit), which
    # the thresholds check then accepts for the records the entry names.
    crosses: tuple[str, ...] = ()

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
            "known_as_of": self.known_as_of.isoformat(),
            "references": list(self.references),
            "crosses": list(self.crosses),
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
        known_as_of=date.fromisoformat(str(raw["known_as_of"])),
        references=tuple(str(r) for r in raw.get("references", [])),
        crosses=tuple(str(c) for c in raw.get("crosses", [])),
    )
