"""The owner's hand-written CRM notes for a featured household, and the check that keeps them honest.

A notes file (`HH-XXXX.notes.toml`, beside the household's script) lists the facts its notes
assert, and each note names the facts it rests on. The check: every amount and every date written
in a note is the amount or date of a fact that note asserts, and every fact matches the record it
names: an event in the household's log, a planted item in the registry, or one of the household's
own records (an agreement, a person, an account, an income line). So a note can colour what the
book holds but cannot add a fact, and so cannot add an unregistered disagreement
(docs/PLAN.md, Choices: "Hand-written notes are written by the owner").
"""

import re
import tomllib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from casebook.model.dates import parse_date
from casebook.model.events import Event
from casebook.model.household import Household
from casebook.model.money import parse_decimal
from casebook.model.registry import RegistryEntry

NOTES_SUFFIX = ".notes.toml"
AUTHOR = "owner"
MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
# A month in full or abbreviated (Sep and Sept both), as a person writes it.
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)[a-z]*\.?"
_NUMBER = r"\d[\d,]*(?:\.\d+)?"
# Amounts as a person writes them: $25,000, USD 25,000, 25,000 dollars, 25,000 US dollars, and any
# number shaped like money (thousands separators, or cents), which a note may not state unchecked.
_AMOUNT = re.compile(
    rf"\$\s?({_NUMBER})|\bUSD\s?({_NUMBER})|({_NUMBER})\s?(?:US\s)?(?:dollars|USD)\b"
    r"|(?<![\w.,-])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d{2})(?![\d%])",
    re.IGNORECASE,
)
# Dates: 2025-05-12, 2025/05/12, 12 May 2025, 12th Sept. 2025, May 12, 2025, 05/12/2025 and 5/12/25
# (month first, as US records write them).
_ISO = re.compile(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b")
_DAY_MONTH = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)? ({_MONTH}),? (\d{{4}})\b", re.IGNORECASE)
_MONTH_DAY = re.compile(rf"\b({_MONTH}) (\d{{1,2}})(?:st|nd|rd|th)?,? (\d{{4}})\b", re.IGNORECASE)
_SLASHED = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})(?![\d/])")


class NotesError(ValueError):
    pass


@dataclass(frozen=True)
class Fact:
    fact_id: str
    says: str
    day: date | None
    amount: Decimal | None
    event_id: str | None
    item_id: str | None
    record: str | None


@dataclass(frozen=True)
class Note:
    note_id: str
    day: date
    facts: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class Notes:
    source: str
    household_id: str
    facts: dict[str, Fact]
    notes: tuple[Note, ...]


def notes_path(script_path: Path) -> Path:
    return script_path.with_name(script_path.stem + NOTES_SUFFIX)


def _fact(raw: dict[str, Any]) -> Fact:
    links = [k for k in ("event_id", "item_id", "record") if k in raw]
    if len(links) != 1:
        raise NotesError(f"fact {raw.get('fact_id', '?')} names one record: an event_id, an item_id or a record")
    day = raw.get("date")
    return Fact(
        fact_id=str(raw["fact_id"]),
        says=str(raw["says"]),
        day=day if isinstance(day, date) else (parse_date(str(day)) if day is not None else None),
        amount=parse_decimal(str(raw["amount"])) if "amount" in raw else None,
        event_id=str(raw["event_id"]) if "event_id" in raw else None,
        item_id=str(raw["item_id"]) if "item_id" in raw else None,
        record=str(raw["record"]) if "record" in raw else None,
    )


def parse_notes(raw: dict[str, Any], source: str) -> Notes:
    try:
        if raw.get("author") != AUTHOR:
            raise NotesError(f"notes are written by the {AUTHOR}")
        facts = [_fact(f) for f in raw.get("facts", [])]
        notes = tuple(
            Note(
                str(n["note_id"]),
                n["date"] if isinstance(n["date"], date) else parse_date(str(n["date"])),
                tuple(str(f) for f in n.get("facts", [])),
                str(n["text"]).strip(),
            )
            for n in raw["notes"]
        )
        household_id = str(raw["household_id"])
    except NotesError as error:
        raise NotesError(f"{source}: {error}") from error
    except (KeyError, TypeError, ValueError) as error:
        raise NotesError(f"{source}: malformed ({error!r})") from error
    by_id = {f.fact_id: f for f in facts}
    if len(by_id) != len(facts):
        raise NotesError(f"{source}: two facts share an ID")
    return Notes(source, household_id, by_id, notes)


def load_notes(path: Path, root: Path) -> Notes:
    with path.open("rb") as handle:
        return parse_notes(tomllib.load(handle), path.relative_to(root).as_posix())


def _amounts(text: str) -> list[Decimal]:
    return [parse_decimal(next(g for g in m.groups() if g).replace(",", "")) for m in _AMOUNT.finditer(text)]


def _month(name: str) -> int:
    return next(i for i, m in enumerate(MONTHS, start=1) if m.lower().startswith(name.lower().rstrip(".")[:3]))


def _dates(text: str) -> tuple[list[date], list[str]]:
    """Every date a note writes, and every date-shaped text that is no real date."""
    found: list[date] = []
    bad: list[str] = []

    def add(year: int, month: int, day: int, written: str) -> None:
        try:
            found.append(date(year, month, day))
        except ValueError:
            bad.append(written)

    for m in _ISO.finditer(text):
        add(int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(0))
    for m in _DAY_MONTH.finditer(text):
        add(int(m.group(3)), _month(m.group(2)), int(m.group(1)), m.group(0))
    for m in _MONTH_DAY.finditer(text):
        add(int(m.group(3)), _month(m.group(1)), int(m.group(2)), m.group(0))
    for m in _SLASHED.finditer(text):
        year = int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0)
        add(year, int(m.group(1)), int(m.group(2)), m.group(0))
    return found, bad


def _known(
    fact: Fact, by_event: dict[str, Event], by_item: dict[str, RegistryEntry], household: Household
) -> date | None:
    """The first day a fact could be known, from the evidence it names: its own date, its event's
    date, the day its planted item's conclusion can be reached, or the date of the household record
    it names (an activity, an agreement, an account's opening, an income line's year end)."""
    days = [fact.day] if fact.day else []
    if fact.event_id is not None and fact.event_id in by_event:
        days.append(by_event[fact.event_id].date)
    if fact.item_id is not None and fact.item_id in by_item:
        days.append(by_item[fact.item_id].known_as_of)
    if fact.record is not None:
        days += _record_known(household, fact.record)
    return max(days) if days else None


def _record_known(household: Household, record: str) -> list[date]:
    for activity in household.crm_activities:
        if activity.activity_id == record:
            return [activity.day]
    for agreement in household.agreements:
        if agreement.agreement_id == record:
            return [agreement.signed]
    for account in household.accounts:
        if account.account_id == record:
            return [account.opened]
    for person in household.members:
        if person.person_id == record:
            return [person.born]
    return [date(i.year, 12, 31) for i in household.income if f"{i.person_id}:{i.kind}:{i.year}" == record]


def _event_matches(fact: Fact, event: Event) -> bool:
    if fact.day is not None and fact.day != event.date:
        return False
    if fact.amount is None:
        return True
    figures = [getattr(event, f) for f in ("amount", "units", "price", "withheld", "share") if hasattr(event, f)]
    return any(isinstance(v, Decimal) and abs(v) == fact.amount for v in figures)


def _money(text: str) -> Decimal | None:
    cleaned = text.replace("$", "").replace(",", "").strip()
    try:
        return parse_decimal(cleaned.removeprefix("-"))
    except ValueError:
        return None


def _entry_matches(fact: Fact, entry: RegistryEntry) -> bool:
    figures = [v for _label, v in entry.figures] + [c for row in entry.table.rows for c in row]
    amounts = {m for m in (_money(v) for v in figures) if m is not None}
    if fact.amount is not None and fact.amount not in amounts:
        return False
    return fact.day is None or fact.day.isoformat() in entry.conclusion or fact.day.isoformat() in figures


def _record_values(household: Household, record: str) -> tuple[set[date], set[Decimal]] | None:
    """The dates and amounts one of the household's own records holds, by its ID."""
    for agreement in household.agreements:
        if agreement.agreement_id == record:
            return {agreement.signed}, set()
    for person in household.members:
        if person.person_id == record:
            return {d for d in (person.born, person.died) if d is not None}, set()
    for account in household.accounts:
        if account.account_id == record:
            dates = {account.opened}
            if account.inherited_from is not None:
                dates |= {account.inherited_from.born, account.inherited_from.died}
            return dates, set()
    for income in household.income:
        if f"{income.person_id}:{income.kind}:{income.year}" == record:
            return set(), {income.amount}
    for activity in household.crm_activities:
        if activity.activity_id == record:
            return {activity.day}, set()
    return None


def check_notes(
    notes: Notes, household: Household, events: tuple[Event, ...], entries: tuple[RegistryEntry, ...]
) -> list[str]:
    problems: list[str] = []
    where = notes.source
    if notes.household_id != household.household_id:
        problems.append(f"{where}: is for {notes.household_id}, not {household.household_id}")
    by_event = {e.event_id: e for e in events}
    by_item = {e.item_id: e for e in entries if e.household_id == household.household_id}
    for fact in notes.facts.values():
        if fact.event_id is not None:
            event = by_event.get(fact.event_id)
            if event is None or not _event_matches(fact, event):
                problems.append(f"{where}: fact {fact.fact_id} does not match event {fact.event_id}")
        elif fact.item_id is not None:
            entry = by_item.get(fact.item_id)
            if entry is None or not _entry_matches(fact, entry):
                problems.append(f"{where}: fact {fact.fact_id} does not match planted item {fact.item_id}")
        else:
            assert fact.record is not None
            values = _record_values(household, fact.record)
            if values is None:
                problems.append(f"{where}: fact {fact.fact_id} names {fact.record}, which the household does not hold")
            elif (fact.day is not None and fact.day not in values[0]) or (
                fact.amount is not None and fact.amount not in values[1]
            ):
                problems.append(f"{where}: fact {fact.fact_id} does not match {fact.record}")
    for note in notes.notes:
        unknown = [f for f in note.facts if f not in notes.facts]
        if unknown:
            problems.append(f"{where}: note {note.note_id} asserts unknown facts {', '.join(unknown)}")
        asserted = [notes.facts[f] for f in note.facts if f in notes.facts]
        amounts = {f.amount for f in asserted if f.amount is not None}
        # The note's own date is not a fact: a date in its text must be one its facts give.
        dates = {f.day for f in asserted if f.day is not None}
        for amount in _amounts(note.text):
            if amount not in amounts:
                problems.append(f"{where}: note {note.note_id} states {amount}, which no fact it asserts holds")
        written, bad = _dates(note.text)
        for day in written:
            if day not in dates:
                problems.append(f"{where}: note {note.note_id} states {day}, which no fact it asserts holds")
        problems += [f"{where}: note {note.note_id} writes {b!r}, which is no date" for b in bad]
        # No future evidence: a note cannot know a fact before the fact exists.
        for fact in asserted:
            known = _known(fact, by_event, by_item, household)
            if known is not None and note.day < known:
                problems.append(
                    f"{where}: note {note.note_id} is dated {note.day}, "
                    f"before fact {fact.fact_id} could be known ({known})"
                )
    return problems
