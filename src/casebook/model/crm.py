"""The CRM's record shapes, and the diff of the CRM sandbox's final state from its start (docs/PLAN.md).

`crm` computes the diff and the runner stores it in the run record; a follow-up task's grader reads it
from there. Both import it from here, so a grader never imports the sandbox.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

# Each collection of a household's CRM, and the field that identifies one of its records.
COLLECTIONS = {"contacts": "person_id", "notes": "note_id", "activities": "activity_id", "agreements": "agreement_id"}
DONE = "done"
SENT_TO_CLIENT = "sent_to_client"

Change = Literal["added", "changed", "removed"]
CHANGES: tuple[Change, ...] = ("added", "changed", "removed")


class CrmDiffError(ValueError):
    pass


def record_order(record_id: str) -> tuple[str | int, ...]:
    """SB-1204-9 before SB-1204-10: digit runs compare as numbers."""
    return tuple(int(part) if index % 2 else part for index, part in enumerate(re.split(r"(\d+)", record_id)))


@dataclass(frozen=True)
class RecordChange:
    household_id: str
    change: Change
    collection: str
    record_id: str
    before: Mapping[str, Any] | None
    after: Mapping[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        entry: dict[str, Any] = {"collection": self.collection, "record_id": self.record_id}
        if self.before is not None:
            entry["before"] = dict(self.before)
        if self.after is not None:
            entry["after"] = dict(self.after)
        return entry


@dataclass(frozen=True)
class CrmDiff:
    """Every record added, changed and removed: by household ID, then added, changed and removed,
    then collection (contacts, notes, activities, agreements), then record ID."""

    changes: tuple[RecordChange, ...]

    def outside(self, household_id: str) -> tuple[RecordChange, ...]:
        """Every record added, changed or removed in a household other than `household_id`."""
        return tuple(change for change in self.changes if change.household_id != household_id)

    def to_dict(self) -> dict[str, Any]:
        households: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for change in self.changes:
            by_kind = households.setdefault(change.household_id, {kind: [] for kind in CHANGES})
            by_kind[change.change].append(change.to_dict())
        return {"households": households}


def parse_crm_diff(stored: Mapping[str, Any]) -> CrmDiff:
    """The diff as a run record holds it (`CrmDiff.to_dict()`), read back."""
    try:
        changes = [
            RecordChange(
                str(household_id),
                kind,
                str(entry["collection"]),
                str(entry["record_id"]),
                entry.get("before"),
                entry.get("after"),
            )
            for household_id, kinds in stored["households"].items()
            for kind in CHANGES
            for entry in kinds.get(kind, [])
        ]
    except (KeyError, TypeError, AttributeError) as error:
        raise CrmDiffError(f"the stored CRM sandbox diff is not one the sandbox writes: {error!r}") from error
    unknown = {c.collection for c in changes} - set(COLLECTIONS)
    if unknown:
        raise CrmDiffError(f"the stored CRM sandbox diff names unknown collections: {sorted(unknown)}")
    return CrmDiff(tuple(changes))
