"""The errata log: the public list of corrections (docs/SPEC.md, Words), each a version, a date, what it corrected
and the household or task IDs it names. The first version has none."""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from casebook.notice import NOTICE

ERRATA_FIELDS = ("version", "date", "correction", "ids")


class ErrataError(ValueError):
    pass


@dataclass(frozen=True)
class Correction:
    version: str
    date: date
    correction: str
    ids: tuple[str, ...]


def _correction(raw: Any, where: str) -> Correction:
    if not isinstance(raw, dict) or sorted(raw) != sorted(ERRATA_FIELDS):  # pyright: ignore[reportUnknownArgumentType]
        raise ErrataError(f"{where}: an entry has exactly {', '.join(ERRATA_FIELDS)}")
    entry: dict[str, Any] = raw  # pyright: ignore[reportUnknownVariableType]
    version, when, text, ids = (entry[f] for f in ERRATA_FIELDS)
    if not isinstance(version, str) or not version.strip():
        raise ErrataError(f"{where}: an entry names its version")
    if not isinstance(text, str) or not text.strip():
        raise ErrataError(f"{where}: an entry says what it corrected")
    if not isinstance(ids, list) or not all(isinstance(i, str) and i.strip() for i in ids):  # pyright: ignore[reportUnknownVariableType]
        raise ErrataError(f"{where}: an entry's ids are a list of household or task IDs")
    try:
        day = date.fromisoformat(str(when))
    except ValueError as error:
        raise ErrataError(f"{where}: {when!r} is not a date (YYYY-MM-DD)") from error
    return Correction(version.strip(), day, text.strip(), tuple(str(i) for i in ids))  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]


def load_errata(path: Path | None) -> list[Correction]:
    """The log's entries, newest version first; none where no log is given. A log named but missing is an error,
    not an empty log (reviewer A, slice 14 round 1)."""
    if path is None:
        return []
    if not path.is_file():
        raise ErrataError(f"{path} is not a file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ErrataError(f"{path.name} is not JSON: {error}") from error
    # The published log carries the notice, as JSON the release copies from published/ does (the owner's decision
    # of 19 November 2026, choice 2); where a log has one, it is the notice word for word.
    if (
        not isinstance(data, dict)
        or not {"entries"} <= set(data) <= {"entries", "notice"}  # pyright: ignore[reportUnknownArgumentType]
        or not isinstance(data["entries"], list)
    ):
        raise ErrataError(f'{path.name}: the log is {{"notice": ..., "entries": [...]}}')
    if data.get("notice", NOTICE) != NOTICE:  # pyright: ignore[reportUnknownMemberType]
        raise ErrataError(f"{path.name}: its notice is not the notice")
    entries: list[Any] = data["entries"]  # pyright: ignore[reportUnknownVariableType]
    corrections = [_correction(e, f"{path.name} entry {i + 1}") for i, e in enumerate(entries)]
    return sorted(corrections, key=lambda c: (c.date, c.version), reverse=True)
