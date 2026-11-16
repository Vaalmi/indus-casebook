"""Copy a household's source sets into a workspace, dropping every row and document known after the cutoff.

The filter works inside files, so a file written later never carries a late row into a
workspace (docs/PLAN.md, reading U2).
"""

import csv
import io
import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

from casebook.model.files import DOCUMENTS_INDEX, csv_text, household_dir, json_text

KNOWN = "known_as_of"


class FixtureError(ValueError):
    pass


def _known(value: object, where: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise FixtureError(f"{where}: known_as_of {value!r} is not a date, so it cannot be filtered") from error


def _filter_json(value: Any, cutoff: date, where: str) -> Any:
    if isinstance(value, dict):
        return {k: _filter_json(v, cutoff, f"{where}.{k}") for k, v in value.items()}
    if isinstance(value, list):
        kept: list[Any] = []
        for index, item in enumerate(value):
            if isinstance(item, dict) and KNOWN in item and _known(item[KNOWN], f"{where}[{index}]") > cutoff:
                continue
            kept.append(_filter_json(item, cutoff, f"{where}[{index}]"))
        return kept
    return value


def _filter_csv(text: str, cutoff: date, where: str) -> str:
    reader = csv.DictReader(io.StringIO(text))
    columns = list(reader.fieldnames or [])
    if KNOWN not in columns:
        raise FixtureError(f"{where} has no known_as_of column, so it cannot be filtered")
    rows = [row for line, row in enumerate(reader, start=2) if _known(row[KNOWN], f"{where} line {line}") <= cutoff]
    return csv_text(columns, rows)


def load_fixtures(book: Path, household_id: str, source_sets: tuple[str, ...], cutoff: date, workspace: Path) -> None:
    folder = book / household_dir(household_id)
    if folder.is_symlink() or folder.parent.is_symlink() or not folder.resolve().is_relative_to(book.resolve()):
        raise FixtureError(
            f"{household_dir(household_id)} is a link; a household's files are read from the book itself only"
        )
    root = folder.resolve()
    for source in source_sets:
        for path in sorted((root / source).rglob("*")):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise FixtureError(f"{relative} is a link; a household's files are read from the book itself only")
            if not path.is_file():
                continue
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix == ".csv":
                target.write_text(_filter_csv(path.read_text(encoding="utf-8"), cutoff, relative), encoding="utf-8")
            elif path.suffix == ".json":
                data = _filter_json(json.loads(path.read_text(encoding="utf-8")), cutoff, relative)
                target.write_text(json_text(data), encoding="utf-8")
            elif path.suffix != ".pdf":
                raise FixtureError(f"{relative}: no way to filter this file by date")
    if "documents" in source_sets:
        index = json.loads((workspace / DOCUMENTS_INDEX).read_text(encoding="utf-8"))
        for document in index["documents"]:
            shutil.copyfile(root / "documents" / document["file"], workspace / "documents" / document["file"])
