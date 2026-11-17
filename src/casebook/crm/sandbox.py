"""The sandbox's state file and the reads and writes an advisor's CRM allows on it.

The state holds the CRM of every household a run may see, by household ID, as the book emits
it: `{"households": {"HH-1204": <crm.json>, ...}, "writes": [...]}`. A real CRM holds every
client, so a write may go to any household in it; the grader, not the sandbox, decides whether
it should have. Each write gets a new ID, `SB-<household digits>-NN`, and an entry in "writes"
with what was written.
"""

import json
import re
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from casebook.model.crm import COLLECTIONS, DONE, SENT_TO_CLIENT

HOUSEHOLDS = "households"
WRITES = "writes"
WRITE_PREFIX = "SB"
PRIMARY = "primary"
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class CrmError(ValueError):
    """A request the CRM refuses, worded for the model that made it."""


def write_state(path: Path, crms: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Write a fresh state holding each household's CRM (by household ID) and return it."""
    state: dict[str, Any] = {HOUSEHOLDS: {hh: dict(crm) for hh, crm in sorted(crms.items())}, WRITES: []}
    save_state(path, state)
    return read_state(path)


def read_state(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: Mapping[str, Any]) -> None:
    """Replace the file whole, so a reader never sees half a write."""
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    partial.replace(path)


def _household(state: Mapping[str, Any], household_id: str) -> dict[str, Any]:
    households: dict[str, Any] = state[HOUSEHOLDS]
    if household_id not in households:
        raise CrmError(f"No household {household_id!r} in the CRM; list_households gives every household ID.")
    return households[household_id]


def _date(value: str) -> str:
    try:
        if not _ISO_DATE.fullmatch(value):
            raise ValueError(value)
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise CrmError(f"Date {value!r} is not a calendar date written YYYY-MM-DD.") from None


def _text(field: str, value: str) -> str:
    if not value.strip():
        raise CrmError(f"The {field} is empty; write what to record.")
    return value.strip()


def list_households(state: Mapping[str, Any]) -> list[dict[str, str]]:
    """Every household's ID and name (its primary contact's), by ID."""
    listed: list[dict[str, str]] = []
    for household_id, crm in sorted(state[HOUSEHOLDS].items()):
        contacts: list[dict[str, Any]] = crm.get("contacts", [])
        primary = next((c for c in contacts if c.get("relationship") == PRIMARY), contacts[0] if contacts else {})
        listed.append({"household_id": household_id, "name": str(primary.get("name", ""))})
    return listed


def read_household(state: Mapping[str, Any], household_id: str) -> dict[str, Any]:
    """One household's records: contacts, notes, activities and agreements."""
    crm = _household(state, household_id)
    return {"household_id": household_id, **{name: crm.get(name, []) for name in COLLECTIONS}}


def _record_write(state: dict[str, Any], household_id: str, tool: str, written: dict[str, Any]) -> str:
    writes: list[dict[str, Any]] = state[WRITES]
    count = sum(1 for w in writes if w["household_id"] == household_id)
    write_id = f"{WRITE_PREFIX}-{household_id.removeprefix('HH-')}-{count + 1:02d}"
    writes.append({"write_id": write_id, "tool": tool, "household_id": household_id, "written": written})
    return write_id


def add_note(state: dict[str, Any], household_id: str, on: str, text: str) -> dict[str, Any]:
    crm = _household(state, household_id)
    written = {"date": _date(on), "text": _text("note text", text)}
    note = {"note_id": _record_write(state, household_id, "add_note", written), **written}
    crm.setdefault("notes", []).append(note)
    return note


def add_activity(
    state: dict[str, Any], household_id: str, on: str, kind: str, summary: str, sent_to_client: bool
) -> dict[str, Any]:
    crm = _household(state, household_id)
    written = {
        "date": _date(on),
        "kind": _text("activity kind", kind),
        "summary": _text("activity summary", summary),
        SENT_TO_CLIENT: sent_to_client,
    }
    activity = {"activity_id": _record_write(state, household_id, "add_activity", written), **written}
    crm.setdefault("activities", []).append(activity)
    return activity


def mark_activity_done(state: dict[str, Any], household_id: str, activity_id: str, on: str) -> dict[str, Any]:
    crm = _household(state, household_id)
    activity = next((a for a in crm.get("activities", []) if a.get("activity_id") == activity_id), None)
    if activity is None:
        raise CrmError(
            f"Household {household_id} has no activity {activity_id!r}; read_household lists its activities."
        )
    if DONE in activity:
        raise CrmError(f"Activity {activity_id} was already marked done on {activity[DONE]}.")
    done_on = _date(on)
    _record_write(state, household_id, "mark_activity_done", {"activity_id": activity_id, DONE: done_on})
    activity[DONE] = done_on
    return activity
