"""The difference between the sandbox's state at the start of a run and at its end.

A follow-up task is graded on the sandbox's final state, and the run record holds this diff.
"""

import json
from collections.abc import Iterator, Mapping
from typing import Any

from casebook.crm.sandbox import HOUSEHOLDS
from casebook.model.crm import CHANGES, COLLECTIONS, CrmDiff, RecordChange, record_order


def _records(crm: Mapping[str, Any] | None, collection: str) -> dict[str, dict[str, Any]]:
    if crm is None:
        return {}
    key = COLLECTIONS[collection]
    return {str(record[key]): record for record in crm.get(collection, [])}


def _household_changes(household_id: str, before: Any, after: Any) -> Iterator[RecordChange]:
    for kind in CHANGES:
        for collection in COLLECTIONS:
            old, new = _records(before, collection), _records(after, collection)
            if kind == "added":
                ids = [i for i in new if i not in old]
            elif kind == "changed":
                ids = [i for i in new if i in old and old[i] != new[i]]
            else:
                ids = [i for i in old if i not in new]
            for record_id in sorted(ids, key=record_order):
                yield RecordChange(household_id, kind, collection, record_id, old.get(record_id), new.get(record_id))


def crm_diff(initial: Mapping[str, Any], final: Mapping[str, Any]) -> CrmDiff:
    """The diff of two sandbox states. Records are copied, so a later change to either state leaves it as it was."""
    before: dict[str, Any] = json.loads(json.dumps(initial[HOUSEHOLDS]))
    after: dict[str, Any] = json.loads(json.dumps(final[HOUSEHOLDS]))
    changes = [
        change
        for household_id in sorted(before.keys() | after.keys())
        for change in _household_changes(household_id, before.get(household_id), after.get(household_id))
    ]
    return CrmDiff(tuple(changes))
