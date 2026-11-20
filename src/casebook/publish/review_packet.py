"""The review packet for the CPA or EA, written to `out/review/<book version>/` with one zip of it.

docs/SPEC.md, What people see: "a packet with ten featured returns, every tax and RMD boundary case, the mapping
from inputs to form lines, and five further household files." What each part holds is the owner's choice 4
(docs/decisions/2026-11-19-slice16-release-choices.md):

- the ten returns: each featured trap's filed return, one per archetype;
- the boundary cases: every planted item of a tax archetype and its near-miss or unresolved twin, each with its tax
  summary; the two lines only in-house code computes (loss carryover and IRA basis, docs/PLAN.md "Choices and why"),
  for every tax unit in the book; and the rule readings the builder made (`book/review/rule_readings.md`);
- the mapping: the twelve forms' line-to-field maps as one table, each return read back line by line, and each
  return's tax unit's facts;
- five background households of tax archetypes drawn with the seed, outside the hand audit's 15 and the private
  pairs, with their tax summaries.

The packet holds tax summaries, which the release refuses, so it is never part of the public release.
"""

import csv
import io
import re
import shutil
from collections.abc import Iterable, Sequence
from importlib.resources import files as package_files
from pathlib import Path
from typing import Any

from casebook.model.archetypes import ARCHETYPES, PRIVATE_PAIRS
from casebook.model.files import (
    METADATA,
    PRICES_CSV,
    REGISTRY,
    SEALED_HOUSEHOLDS,
    SECURITIES_CSV,
    event_log_path,
    household_dir,
    json_text,
    read_json,
    read_manifest,
    tax_summary_path,
)
from casebook.notice import NOTICE
from casebook.publish.packets import NOTICE_FILE, book_file
from casebook.publish.zips import write_zip
from casebook.seeding import derive_rng
from casebook.site import FEATURED, RETURN_FORMS
from casebook.tax.forms import FORMS, read_back
from casebook.tax.forms.maps import field_map

REPO = Path(__file__).resolve().parents[3]
AUDIT_LOG = REPO / "published" / "audit" / "audit-log.csv"
RULE_READINGS = REPO / "book" / "review" / "rule_readings.md"

# A tax archetype is one whose planted item is a tax or RMD situation: every archetype but 10, fee and IPS drift
# (docs/SPEC.md, Archetypes).
NOT_TAX_ARCHETYPES = (10,)
TAX_ARCHETYPES = tuple(a for a in ARCHETYPES if a not in NOT_TAX_ARCHETYPES)
# A twin is a boundary case when it sits just short of its trap's situation or cannot be settled from the files.
BOUNDARY_TWINS = ("near_miss", "unresolved")
FURTHER_HOUSEHOLDS = 5
DRAW_SUBJECT = "review-packet"
# The lines of a tax summary whose second calculator is the keys' own code, not Tax-Calculator.
IN_HOUSE = "keys"

README = "README.md"
INDEX = "packet.json"
READINGS = "boundary/rule_readings.md"
CASES = "boundary/cases.json"
IN_HOUSE_LINES = "boundary/in_house_lines.csv"
FORM_LINES = "mapping/form_lines.csv"
READ_BACK = "mapping/returns_read_back.csv"

_MAP_ENTRY = re.compile(
    r'^(?:"(?P<quoted>[^"]+)"|(?P<bare>[A-Za-z0-9_]+))\s*=\s*"(?P<field>[^"]+)"\s*#\s*(?P<label>.*)$'
)


class ReviewPacketError(ValueError):
    pass


def _csv(columns: Sequence[str], rows: Iterable[Sequence[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _json(data: dict[str, Any]) -> bytes:
    return json_text({"notice": NOTICE, **data}).encode("utf-8")


def form_labels(form: str) -> dict[str, str]:
    """Each line's label, as its map's comment gives it (the field's own label from the form's XFA)."""
    text = (package_files("casebook.tax.forms") / "maps" / f"{form}.toml").read_text(encoding="utf-8")
    labels: dict[str, str] = {}
    for line in text.splitlines():
        found = _MAP_ENTRY.match(line)
        if found:
            labels[found["quoted"] or found["bare"]] = found["label"].strip()
    missing = sorted(set(field_map(form)) - set(labels))
    if missing:
        raise ReviewPacketError(f"maps/{form}.toml gives no label for {', '.join(missing)}")
    return labels


def form_lines_table() -> bytes:
    """The twelve forms' line-to-field maps as one table, in the order a return files them."""
    rows: list[list[str]] = []
    for form in FORMS:
        labels = form_labels(form)
        rows += [[form, RETURN_FORMS[form], key, field, labels[key]] for key, field in field_map(form).items()]
    return _csv(("form", "form_name", "line", "pdf_field", "label"), rows)


def form_of(pdf: str) -> str:
    """`f8949-D-1.pdf` is Form 8949; `f8606-P-1204-2.pdf` is Form 8606."""
    return pdf.removesuffix(".pdf").partition("-")[0]


def audited(log: Path) -> frozenset[str]:
    """The hand audit's households, by its published log."""
    with log.open(encoding="utf-8", newline="") as handle:
        return frozenset(row["household_id"] for row in csv.DictReader(handle))


def draw_further(households: list[dict[str, Any]], audit: frozenset[str], seed: int) -> list[str]:
    """Five background households of tax archetypes, outside the audited 15, drawn with the seed."""
    candidates = sorted(
        str(h["household_id"])
        for h in households
        if h["set"] != FEATURED and h["archetype"] in TAX_ARCHETYPES and h["household_id"] not in audit
    )
    if len(candidates) < FURTHER_HOUSEHOLDS:
        raise ReviewPacketError(
            f"the book has {len(candidates)} background households of tax archetypes outside the audit, and the "
            f"packet needs {FURTHER_HOUSEHOLDS}: build the full book (`casebook build`, background households included)"
        )
    return sorted(derive_rng(DRAW_SUBJECT, seed).sample(candidates, FURTHER_HOUSEHOLDS))


def boundary_cases(households: list[dict[str, Any]], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every planted item of a tax archetype, then its twin when that twin is a near miss or unresolved."""
    by_id = {str(h["household_id"]): h for h in households}
    twins = {(h["archetype"], h["pair"]): h for h in households if h["role"] == "twin"}
    cases: list[dict[str, Any]] = []
    for entry in sorted(entries, key=lambda e: (str(e["household_id"]), str(e["item_id"]))):
        trap = by_id[str(entry["household_id"])]
        if trap["archetype"] not in TAX_ARCHETYPES:
            continue
        cases.append(_case(trap, {"planted_item": entry}))
        twin = twins.get((trap["archetype"], trap["pair"]))
        if twin is not None and twin["twin_kind"] in BOUNDARY_TWINS:
            cases.append(_case(twin, {"trap": trap["household_id"], "explanation": twin["explanation"]}))
    return cases


def _case(household: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    household_id = str(household["household_id"])
    return {
        "household_id": household_id,
        "archetype": household["archetype"],
        "archetype_name": household["archetype_name"],
        "set": household["set"],
        "pair": household["pair"],
        "role": household["role"],
        "twin_kind": household["twin_kind"],
        "tax_summary": f"tax_summaries/{household_id}.json",
        **detail,
    }


def in_house_lines(book: Path, household_ids: Iterable[str]) -> bytes:
    """Each tax unit's loss carryover and IRA basis, from the engine and from the keys' own code."""
    rows: list[list[str]] = []
    for household_id in sorted(household_ids):
        for line in read_json(book, tax_summary_path(household_id))["comparisons"]:
            if line["against"] == IN_HOUSE:
                agrees = "yes" if line["agrees"] else "no"
                rows.append([household_id, line["tax_unit_id"], line["field"], line["engine"], line["other"], agrees])
    return _csv(("household_id", "tax_unit_id", "line", "engine", "keys", "agrees"), rows)


def _readme(version: str, returns: list[dict[str, Any]], cases: list[dict[str, Any]], further: list[str]) -> bytes:
    traps = sum(1 for c in cases if c["role"] == "trap")
    returned = "\n".join(f"  - archetype {r['archetype']}: {r['household_id']}, {r['tax_unit_id']}" for r in returns)
    text = f"""# Review packet, book {version}

{NOTICE}

**Nothing in this packet has been reviewed.** It is the material for the CPA or EA review (docs/SPEC.md, What people
see): every return, tax summary, answer and reading in it is the builder's work, unchecked by a qualified practitioner.
It holds the tax summaries the public release refuses, so it is never part of the public release.

## What is inside

- `returns/<household>/<tax unit>/`: the ten featured traps' 2025 returns, one per archetype, as filed in the
  book (every page watermarked "unreviewed"), and `facts.json`, the tax unit's 2025 facts the return was filled from.
{returned}
- `mapping/form_lines.csv`: the twelve forms' line-to-field maps as one table: each line's key, the PDF field that
  holds it, and the field's own label on the official form.
- `mapping/returns_read_back.csv`: every filled line of the ten returns, read back from the PDFs.
- `boundary/cases.json`: every planted tax or RMD item in the book ({traps} items, the registry's entry for each)
  and its twin where that twin is a near miss or unresolved (with the twin's explanation), {len(cases)} cases in
  all, each naming its tax summary.
- `boundary/in_house_lines.csv`: the two lines of every tax summary in the book that only in-house code computes,
  the loss carryover and IRA basis, as the engine and the keys' own code each give them. No outside calculator
  computes either, so the two in-house implementations are the only check on them. The same holds for the taxable
  part of IRA, 401(k) and inherited-IRA distributions: Tax-Calculator takes it from the keys' own Form 8606.
- `boundary/rule_readings.md`: the readings of tax and RMD rules the builder made in building the book, each with
  where it is recorded.
- `households/<household>/`: five further background households of tax archetypes, with their four source sets:
  {", ".join(further)}. They were drawn with the book's seed, outside the 15 households of the hand audit and
  outside the private pairs.
- `tax_summaries/<household>.json`: the 2025 tax summary of every household above: each tax unit's figures from the
  in-house engine, and each figure's comparison with Tax-Calculator or the keys' own code.
- `securities/` and `metadata.json`: the book's securities list, its synthetic prices and its metadata.
- `packet.json`: this list as data.
"""
    return text.encode("utf-8")


def review_packet(book: Path, audit_log: Path = AUDIT_LOG, rule_readings: Path = RULE_READINGS) -> dict[str, bytes]:
    """The packet's files, by path inside it."""
    manifest = read_manifest(book)
    digests = manifest.files
    households: list[dict[str, Any]] = read_json(book, SEALED_HOUSEHOLDS)["households"]
    private = sorted(
        str(h["household_id"])
        for h in households
        if h["set"] != FEATURED and (h["archetype"], h["pair"]) in PRIVATE_PAIRS
    )
    if private:
        raise ReviewPacketError(
            f"{', '.join(private)}: a private pair's household; write the packet from the public book"
        )
    out: dict[str, bytes] = {NOTICE_FILE: (NOTICE + "\n").encode("utf-8")}

    traps = {h["archetype"]: str(h["household_id"]) for h in households if h["set"] == FEATURED and h["role"] == "trap"}
    missing = sorted(set(ARCHETYPES) - set(traps))
    if missing:
        raise ReviewPacketError(f"the book has no featured trap of archetype {', '.join(map(str, missing))}")
    returns: list[dict[str, Any]] = []
    read_rows: list[list[str]] = []
    for archetype in sorted(traps):
        household_id = traps[archetype]
        prefix = f"sealed/{household_id}/returns/"
        units = sorted({n.removeprefix(prefix).partition("/")[0] for n in digests if n.startswith(prefix)})
        if len(units) != 1:
            raise ReviewPacketError(
                f"{household_id} files {len(units)} returns; the packet takes each trap's one return"
            )
        unit = units[0]
        returns.append({"household_id": household_id, "archetype": archetype, "tax_unit_id": unit})
        facts = [f for f in read_json(book, event_log_path(household_id))["tax_units"] if f["tax_unit_id"] == unit]
        if len(facts) != 1:
            raise ReviewPacketError(f"{household_id}'s event log holds no facts for {unit}")
        out[f"returns/{household_id}/{unit}/facts.json"] = _json({"facts": facts[0]})
        for name in sorted(n for n in digests if n.startswith(f"{prefix}{unit}/")):
            pdf = book_file(book, name, digests)
            file = name.rpartition("/")[2]
            out[f"returns/{household_id}/{unit}/{file}"] = pdf
            for line, value in read_back(form_of(file), pdf).items():
                read_rows.append(
                    [household_id, unit, file, form_of(file), line, "checked" if value is True else str(value)]
                )
    out[FORM_LINES] = form_lines_table()
    out[READ_BACK] = _csv(("household_id", "tax_unit_id", "file", "form", "line", "value"), read_rows)

    cases = boundary_cases(households, read_json(book, REGISTRY)["entries"])
    out[CASES] = _json({"cases": cases})
    out[IN_HOUSE_LINES] = in_house_lines(book, (str(h["household_id"]) for h in households))
    out[READINGS] = rule_readings.read_bytes()

    further = draw_further(households, audited(audit_log), manifest.seed)
    for household_id in further:
        prefix = household_dir(household_id) + "/"
        out |= {name: book_file(book, name, digests) for name in sorted(digests) if name.startswith(prefix)}
    summarized = sorted({*(r["household_id"] for r in returns), *(c["household_id"] for c in cases), *further})
    for household_id in summarized:
        out[f"tax_summaries/{household_id}.json"] = book_file(book, tax_summary_path(household_id), digests)
    out |= {name: book_file(book, name, digests) for name in (SECURITIES_CSV, PRICES_CSV, METADATA)}

    out[INDEX] = _json(
        {
            "book_version": manifest.version,
            "seed": manifest.seed,
            "reviewed": False,
            "returns": returns,
            "boundary_cases": [c["household_id"] for c in cases],
            "further_households": further,
            "tax_summaries": summarized,
        }
    )
    out[README] = _readme(manifest.version, returns, cases, further)
    return out


def packet_zip(folder: Path) -> Path:
    """Where the zip of a packet folder goes: beside it, `review-packet-<book version>.zip`."""
    return folder.parent / f"review-packet-{folder.name}.zip"


def write_review_packet(
    book: Path, out: Path, audit_log: Path = AUDIT_LOG, rule_readings: Path = RULE_READINGS
) -> Path:
    """Writes `out/<book version>/` and its zip beside it (`packet_zip`); returns the folder. A folder already there
    is replaced, so it holds exactly what the zip holds."""
    packet = review_packet(book, audit_log, rule_readings)
    folder = out / read_manifest(book).version
    if folder.exists():
        shutil.rmtree(folder)
    for name, data in packet.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    packet_zip(folder).write_bytes(write_zip(packet))
    return folder
