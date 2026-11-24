"""Case packets: one zip per featured household, its source sets as the book has them and a separate answer sheet.

docs/SPEC.md, What people see: "one zip per featured household with its source files and a separate answer sheet.
Tax answer sheets are absent until review." The answer sheet holds what the household's page already shows (the
owner's decision on U4): the planted item's justified conclusion with its figures, or the twin's explanation; and
the published answer keys of the household's tasks that are not held. The household's tax summary (the held "tax
answer sheet") and every held key stay out (docs/decisions/2026-11-19-slice16-release-choices.md, choice 3(a)).
"""

import hashlib
import json
from pathlib import Path
from typing import Any

from casebook.model.files import (
    MANIFEST,
    METADATA,
    PRICES_CSV,
    REGISTRY,
    SEALED_HOUSEHOLDS,
    SECURITIES_CSV,
    household_dir,
    json_text,
    read_json,
    read_manifest,
    tax_summary_path,
)
from casebook.notice import NOTICE
from casebook.publish.zips import write_zip
from casebook.review_statement import is_held, statement_of
from casebook.site import FEATURED
from casebook.tasks.task import load_task

ANSWER_SHEET = "answer-sheet.json"
# The household's tax answer sheet, once a review statement covers its return: its 2025 tax summary under the
# reviewed notice (docs/PLAN.md, What stays held: "the tax answer sheets in the case packets"; reviewers A and B,
# slice 17 round 1, S2).
TAX_ANSWER_SHEET = "tax-answer-sheet.json"
NOTICE_FILE = "NOTICE.txt"
# What a packet's answer sheet says is held until the tax review, besides the held tasks' keys.
TAX_SUMMARY_HELD = "the household's 2025 tax summary"


class PacketError(ValueError):
    pass


def book_file(book: Path, name: str, digests: dict[str, str]) -> bytes:
    """A book file's bytes, refused unless the manifest lists it with those bytes' hash."""
    data = (book / name).read_bytes()
    if digests.get(name) != hashlib.sha256(data).hexdigest():
        raise PacketError(f"{name} is not the file the book's {MANIFEST} lists")
    return data


def _planted_item(entry: dict[str, Any]) -> dict[str, Any]:
    """The registry entry as the household page shows it: no references, dates or cited real price range."""
    return {
        "item_id": entry["item_id"],
        "title": entry["title"],
        "kind": entry["kind"],
        "sources": entry["sources"],
        "justified_conclusion": entry["justified_conclusion"],
        "figures": entry["figures"],
        "table": entry["table"],
    }


def answer_sheet(
    household: dict[str, Any],
    entries: list[dict[str, Any]],
    keys: dict[str, dict[str, Any]],
    held: list[str],
    tax_reviewed: bool = False,
) -> dict[str, Any]:
    """`keys`: the published key of each of the household's tasks that is not held, by task ID; `held`: the IDs of
    its held tasks, whose keys stay out; `tax_reviewed`: whether a review statement covers its return, so its tax
    answer sheet ships beside this one."""
    planted = [e for e in entries if e["household_id"] == household["household_id"]]
    return {
        "notice": NOTICE,
        "household_id": household["household_id"],
        "archetype": household["archetype"],
        "archetype_name": household["archetype_name"],
        "pair": household["pair"],
        "role": household["role"],
        "twin_kind": household["twin_kind"],
        "planted_items": [_planted_item(e) for e in planted],
        "explanation": household["explanation"],
        "keys": [{"task_id": task_id, "key": keys[task_id]} for task_id in sorted(keys)],
        "held_until_review": {"task_keys": sorted(held), "tax_summary": None if tax_reviewed else TAX_SUMMARY_HELD},
        # Only once reviewed, so a sheet before any review stays byte for byte what the preview shipped.
        **({"tax_answer_sheet": TAX_ANSWER_SHEET} if tax_reviewed else {}),
    }


def case_packets(book: Path, keys: Path, tasks: Path) -> dict[str, bytes]:
    """`{"HH-XXXX.zip": bytes}` for each featured household. `keys` is the published keys' folder
    (`published/keys/`), read at the book's version, as `casebook site` reads it; `tasks` the public task files."""
    manifest = read_manifest(book)
    digests = manifest.files
    shared = {name: book_file(book, name, digests) for name in (SECURITIES_CSV, PRICES_CSV, METADATA)}
    entries: list[dict[str, Any]] = read_json(book, REGISTRY)["entries"]
    loaded = [load_task(path) for path in sorted(tasks.glob("*.toml"))]
    keys_dir = keys / manifest.version
    # A tax task a review statement covers is no longer held: its key joins the answer sheet.
    statement = statement_of(book)
    packets: dict[str, bytes] = {}
    featured = [h for h in read_json(book, SEALED_HOUSEHOLDS)["households"] if h["set"] == FEATURED]
    for household in sorted(featured, key=lambda h: str(h["household_id"])):
        household_id = str(household["household_id"])
        prefix = household_dir(household_id) + "/"
        files = {name: book_file(book, name, digests) for name in sorted(digests) if name.startswith(prefix)}
        if not files:
            raise PacketError(f"{household_id} is featured but the book's {MANIFEST} lists none of its files")
        mine = [t for t in loaded if t.household_id == household_id]
        published: dict[str, dict[str, Any]] = {}
        for task in (t for t in mine if not is_held(t, statement)):
            key = keys_dir / f"{task.task_id}.json"
            if not key.is_file():
                raise PacketError(f"{task.task_id} is not held, but {key} is missing")
            published[task.task_id] = json.loads(key.read_text(encoding="utf-8"))
        reviewed = statement is not None and statement.covers_return(household_id)
        held = [t.task_id for t in mine if is_held(t, statement)]
        sheet = answer_sheet(household, entries, published, held, reviewed)
        files |= shared
        files[NOTICE_FILE] = (NOTICE + "\n").encode("utf-8")
        files[ANSWER_SHEET] = json_text(sheet).encode("utf-8")
        if statement is not None and reviewed:
            summary = read_json(book, tax_summary_path(household_id))
            files[TAX_ANSWER_SHEET] = json_text({**summary, "notice": statement.notice}).encode("utf-8")
        packets[f"{household_id}.zip"] = write_zip(files)
    return packets
