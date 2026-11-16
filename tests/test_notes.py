"""Slice 5: the owner's hand-written notes, and the check that ties every amount and date to a fact."""

import dataclasses
import json
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from casebook.build import BuildError, build_book
from casebook.generate.notes import Fact, Note, Notes, check_notes
from casebook.generate.script import load_scripts
from casebook.generate.simulate import simulate
from casebook.model.events import Event
from casebook.model.household import Household
from casebook.model.registry import RegistryEntry
from casebook.plant import PlantContext, plant
from casebook.replay import replay
from casebook.securities.market import build_market
from casebook.securities.master import load_master
from casebook.sources.context import SNAPSHOT_DAYS

from .conftest import FEATURED, SCRIPTS, SEED

# A notes file of the kind the owner writes from the fact sheet. Its facts name an event (the
# joint account's 25,000 contribution on 2025-05-12), the planted item and its overbilling, and the
# householding letter. Each note's amounts and dates are among its facts'.
NOTES = '''
household_id = "HH-4821"
author = "owner"

[[facts]]
fact_id = "F-01"
event_id = "E-4821-0015"
date = 2025-05-12
amount = "25000.00"
says = "Adaeze and Henrik added $25,000 to the joint account"

[[facts]]
fact_id = "F-02"
record = "AGR-4821-3"
date = 2024-11-18
says = "The householding letter, signed by all three"

[[facts]]
fact_id = "F-03"
item_id = "PI-0001"
amount = "290.25"
says = "The quarter to 31 March 2026 was overbilled by this much"

[[notes]]
note_id = "N-4821-01"
date = 2025-05-13
facts = ["F-01"]
text = """
Adaeze called: they sent $25,000 into the joint account on 12 May 2025 from Henrik's bonus.
"""

[[notes]]
note_id = "N-4821-02"
date = 2026-04-14
facts = ["F-02", "F-03"]
text = """
Ngozi asked why her fee went up. The letter of 2024-11-18 should have joined her account to her
parents' group; the last quarter alone looks $290.25 too high. Raising it with billing.
"""
'''


def with_notes(tmp_path: Path, text: str) -> Path:
    scripts = tmp_path / "scripted"
    shutil.copytree(SCRIPTS, scripts)
    (scripts / "archetype-10" / "HH-4821.notes.toml").write_text(text)
    return scripts


def test_the_owners_notes_replace_the_template_notes(tmp_path: Path) -> None:
    build_book(SEED, tmp_path / "book", with_notes(tmp_path, NOTES))
    crm = json.loads((tmp_path / "book" / "households" / "HH-4821" / "crm" / "crm.json").read_text())
    assert [(n["note_id"], n["author"], n["date"]) for n in crm["notes"]] == [
        ("N-4821-01", "owner", "2025-05-13"),
        ("N-4821-02", "owner", "2026-04-14"),
    ]
    assert crm["notes"][1]["text"].startswith("Ngozi asked why her fee went up.")
    # The facts stay out of the book: the AI under test sees the notes, not what they rest on.
    assert "F-01" not in json.dumps(crm)
    twin = json.loads((tmp_path / "book" / "households" / "HH-7350" / "crm" / "crm.json").read_text())
    assert {n["author"] for n in twin["notes"]} == {"template"}


@pytest.mark.parametrize(
    ("old", "new", "problem"),
    [
        # An amount the note's facts do not hold.
        (
            "they sent $25,000 into",
            "they sent $26,000 into",
            "note N-4821-01 states 26000, which no fact it asserts holds",
        ),
        (
            "looks $290.25 too high",
            "looks 300 dollars too high",
            "note N-4821-02 states 300, which no fact it asserts holds",
        ),
        # A date the note's facts do not hold.
        (
            "on 12 May 2025 from",
            "on 14 May 2025 from",
            "note N-4821-01 states 2025-05-14, which no fact it asserts holds",
        ),
        ("The letter of 2024-11-18", "The letter of November 20, 2024", "states 2024-11-20, which no fact"),
        # A fact that does not match the record it names.
        ('amount = "25000.00"', 'amount = "26000.00"', "fact F-01 does not match event E-4821-0015"),
        ('amount = "290.25"', 'amount = "508.56"', "fact F-03 does not match planted item PI-0001"),
        ("date = 2024-11-18", "date = 2024-11-19", "fact F-02 does not match AGR-4821-3"),
        (
            'record = "AGR-4821-3"',
            'record = "AGR-4821-9"',
            "fact F-02 names AGR-4821-9, which the household does not hold",
        ),
        # A note asserting a fact the file does not list.
        ('facts = ["F-01"]', 'facts = ["F-01", "F-09"]', "note N-4821-01 asserts unknown facts F-09"),
        # Reviewers A and B, slice 5 round 1: forms the check did not read.
        ("they sent $25,000 into", "they sent 26,000.00 into", "note N-4821-01 states 26000.00, which no fact"),
        ("they sent $25,000 into", "they sent 26,000 US dollars into", "note N-4821-01 states 26000, which no fact"),
        ("on 12 May 2025 from", "on 05/14/2025 from", "note N-4821-01 states 2025-05-14, which no fact"),
        ("on 12 May 2025 from", "on Sept. 14th, 2025 from", "note N-4821-01 states 2025-09-14, which no fact"),
        ("on 12 May 2025 from", "on 13/45/2025 from", "note N-4821-01 writes '13/45/2025', which is no date"),
        # The note's own date is no fact: B's probe wrote it into the text.
        ("on 12 May 2025 from", "on 13 May 2025 from", "note N-4821-01 states 2025-05-13, which no fact"),
        # No future evidence: a note dated before the contribution it reports (A-S3, B-S2).
        (
            'note_id = "N-4821-01"\ndate = 2025-05-13',
            'note_id = "N-4821-01"\ndate = 2025-01-02',
            "dated 2025-01-02, before fact F-01 could be known \\(2025-05-12\\)",
        ),
        # The planted item's workings run to the fee of 2026-04-02.
        (
            'note_id = "N-4821-02"\ndate = 2026-04-14',
            'note_id = "N-4821-02"\ndate = 2026-03-30',
            "before fact F-03 could be known \\(2026-04-02\\)",
        ),
    ],
)
def test_a_note_that_says_more_than_its_facts_fails_the_build(tmp_path: Path, old: str, new: str, problem: str) -> None:
    assert NOTES.count(old) == 1
    with pytest.raises(BuildError, match=problem):
        build_book(SEED, tmp_path / "book", with_notes(tmp_path, NOTES.replace(old, new)))
    assert not (tmp_path / "book").exists()


def test_notes_must_be_the_owners(tmp_path: Path) -> None:
    with pytest.raises(BuildError, match="notes are written by the owner"):
        build_book(SEED, tmp_path / "book", with_notes(tmp_path, NOTES.replace('author = "owner"', 'author = "model"')))


def test_a_fact_names_exactly_one_record(tmp_path: Path) -> None:
    two = NOTES.replace('record = "AGR-4821-3"', 'record = "AGR-4821-3"\nevent_id = "E-4821-0015"')
    with pytest.raises(BuildError, match="names one record"):
        build_book(SEED, tmp_path / "book", with_notes(tmp_path, two))


def test_the_fact_sheet_lists_what_a_note_may_cite(book: Path, tmp_path: Path) -> None:
    from casebook.generate.facts import write_fact_sheets

    written = write_fact_sheets(book, tmp_path / "facts")
    assert sorted(p.name for p in written) == [f"{h}.md" for h in FEATURED]
    sheet = (tmp_path / "facts" / "HH-4821.md").read_text()
    for line in (
        "| `E-4821-0015` | 2025-05-12 | contribution | account_id SYN-48210001, amount 25000.00 |",
        "| `AGR-4821-3` | householding | 2024-11-18 |",
        "## Planted item `PI-0001` (`item_id`)",
        "| 2026-03-31 | 2026-04-02 | $1,907,466.87 | $4,605.18 | $4,314.93 | $290.25 |",
        'household_id = "HH-4821"',
    ):
        assert line in sheet, line


def household_events_entries(household: str) -> tuple[Household, tuple[Event, ...], tuple[RegistryEntry, ...]]:
    script = next(s for s in load_scripts(SCRIPTS) if s.household.household_id == household)
    market = build_market(load_master(), SEED)
    simulation = simulate(script, market)
    context = PlantContext(
        script, simulation.events, replay(simulation.events, SNAPSHOT_DAYS), simulation.quarters, market
    )
    return script.household, simulation.events, plant(context).entries


def one_note(household: str, fact: Fact, day: date, text: str) -> Notes:
    return Notes("n", household, {fact.fact_id: fact}, (Note("N-1", day, (fact.fact_id,), text),))


def test_a_note_cannot_cite_a_planted_items_figure_before_its_conclusion_can_be_reached() -> None:
    # Reviewer A, slice 5 round 2: the pro-rata figure needs the 31 December 2025 balances.
    hh, events, entries = household_events_entries("HH-1204")
    fact = Fact("F-1", "the taxable part", None, Decimal("6748.00"), None, "PI-0002", None)
    early = one_note("HH-1204", fact, date(2025, 1, 2), "The taxable part of the conversion is $6,748.00.")
    assert check_notes(early, hh, events, entries) == [
        "n: note N-1 is dated 2025-01-02, before fact F-1 could be known (2025-12-31)"
    ]
    after = one_note("HH-1204", fact, date(2026, 1, 5), "The taxable part of the conversion is $6,748.00.")
    assert check_notes(after, hh, events, entries) == []


def test_a_note_cannot_report_a_crm_record_before_it_exists() -> None:
    # Reviewers A and B, slice 5 round 2: a record fact with no date of its own took no date.
    hh, events, entries = household_events_entries("HH-6047")
    fact = Fact("F-1", "the charity's letter", None, None, None, None, "CA-6047-02")
    early = one_note("HH-6047", fact, date(2025, 1, 2), "The charity's acknowledgment is in and filed.")
    assert check_notes(early, hh, events, entries) == [
        "n: note N-1 is dated 2025-01-02, before fact F-1 could be known (2025-10-06)"
    ]


def test_a_deadline_among_an_items_figures_does_not_delay_it() -> None:
    # Reviewer B, slice 5 round 2: a future deadline in the figures made a current note look early.
    hh, events, entries = household_events_entries("HH-4821")
    entry = dataclasses.replace(entries[0], figures=(*entries[0].figures, ("Account to be emptied by", "2033-12-31")))
    fact = Fact("F-1", "overbilled", None, Decimal("290.25"), None, "PI-0001", None)
    note = one_note("HH-4821", fact, date(2026, 4, 15), "The last quarter is $290.25 too high.")
    assert check_notes(note, hh, events, (entry,)) == []
