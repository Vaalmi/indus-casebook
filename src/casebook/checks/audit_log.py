"""The audit log: the worksheet as the owner fills it, and the check that it shows the hand audit done.

Done means every worksheet line is present and unchanged, every line checked, every result `ok` or
`defect`, every defect noted, and no arithmetic defect open: a defect closes when `fixed_in` names the
book version that fixes it.
"""

import re
from collections import Counter
from pathlib import Path

from casebook.checks.audit_sheet import COLUMNS, STATED_COLUMNS
from casebook.model.files import FileFormatError, read_csv

YES = "yes"
OK = "ok"
DEFECT = "defect"
_VERSION = re.compile(r"\d+\.\d+\.\d+")

type LineKey = tuple[str, str]


def _rows(path: Path) -> list[dict[str, str]]:
    return read_csv(path.parent, path.name, COLUMNS)


def _key(row: dict[str, str]) -> LineKey:
    return row["household_id"], row["line"]


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def audit_log_problems(log: Path, worksheet: Path) -> list[str]:
    """Each problem with the log against the worksheet, by household and line; none when the audit is done. The
    worksheet's folder names the book version it audits (`out/audit/<version>/worksheet.csv`); a fix must ship
    in a later one."""
    audited = _version(worksheet.parent.name) if _VERSION.fullmatch(worksheet.parent.name) else None
    sheet = {_key(r): r for r in _rows(worksheet)}
    try:
        rows = _rows(log)
    except FileFormatError as error:
        return [str(error)]
    filled = {_key(r): r for r in rows}
    problems = [
        f"{h} line {n}: in the log {count} times" for (h, n), count in Counter(map(_key, rows)).items() if count > 1
    ]
    for key, row in sheet.items():
        where = f"{key[0]} line {key[1]}"
        entry = filled.get(key)
        if entry is None:
            problems.append(f"{where}: missing from the log")
            continue
        changed = [column for column in STATED_COLUMNS if entry[column] != row[column]]
        if changed:
            problems.append(f"{where}: {', '.join(changed)} changed from the worksheet")
        if entry["checked"] != YES:
            problems.append(f"{where}: not checked")
        if entry["result"] not in (OK, DEFECT):
            problems.append(f"{where}: result is {entry['result']!r}, not {OK} or {DEFECT}")
        if entry["result"] == DEFECT:
            if not entry["note"].strip():
                problems.append(f"{where}: a defect with no note")
            if not entry["fixed_in"]:
                problems.append(f"{where}: an arithmetic defect still open")
            elif not _VERSION.fullmatch(entry["fixed_in"]):
                problems.append(f"{where}: fixed in {entry['fixed_in']!r}, which is not a book version")
            elif audited is not None and _version(entry["fixed_in"]) <= audited:
                # A fix ships as a new book version (docs/PLAN.md, slice 12; reviewers A and B, round 1 notes).
                problems.append(
                    f"{where}: fixed in {entry['fixed_in']}, not a version after the audited {worksheet.parent.name}"
                )
    problems += [f"{h} line {n}: not a worksheet line" for h, n in sorted(set(filled) - set(sheet))]
    return problems
