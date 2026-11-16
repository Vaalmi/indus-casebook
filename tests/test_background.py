"""Slice 6: the background households, drawn from the seed, with template notes and no model call."""

import json
import os
import shutil
import socket
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from casebook.build import build_book
from casebook.checks import check_book, thresholds
from casebook.generate.background import background_ids
from casebook.model.files import ACCOUNTS_COLUMNS, ACCOUNTS_CSV, TransactionRow, read_csv, read_transactions
from casebook.sources.crm import TEMPLATES

from .conftest import SCRIPTS, SEED


def test_background_ids_are_drawn_from_their_own_range_without_repeats() -> None:
    ids = background_ids(SEED)
    assert len(ids) == 80 == len(set(ids))
    assert all(100 <= int(i.removeprefix("HH-")) <= 999 for i in ids)
    assert background_ids(SEED) == ids and background_ids(SEED + 1) != ids


@pytest.fixture(scope="module")
def drawn(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """All 80 background households, built with every outside program blocked."""
    out = tmp_path_factory.mktemp("background") / "book"
    empty = tmp_path_factory.mktemp("no-scripts")
    with pytest.MonkeyPatch.context() as patch:

        def refused(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("the build reached outside: a model, a network or a program")

        patch.setattr(socket.socket, "connect", refused)
        patch.setattr(socket, "create_connection", refused)
        patch.setattr(subprocess, "Popen", refused)
        patch.setattr(subprocess, "run", refused)
        build_book(SEED, out, empty, background=True)
    return out


def test_the_build_draws_background_households_with_no_model_call(drawn: Path) -> None:
    # Building under a blocked network and blocked subprocesses proves no model was called.
    sealed = json.loads((drawn / "sealed" / "households.json").read_text())["households"]
    assert len(sealed) == 80 and {h["set"] for h in sealed} == {"background"}
    assert sorted((h["archetype"], h["pair"], h["role"]) for h in sealed) == sorted(
        (a, pair, role) for a in range(1, 11) for pair in (2, 3, 4, 5) for role in ("trap", "twin")
    )
    report = check_book(drawn)
    assert report.passed and len(report.lines) == 80 * 9


def test_every_background_note_re_renders_from_its_template_and_slots(drawn: Path) -> None:
    notes = [
        note
        for crm in sorted((drawn / "households").glob("*/crm/crm.json"))
        for note in json.loads(crm.read_text())["notes"]
    ]
    assert notes
    for note in notes:
        assert note["author"] == "template"
        assert TEMPLATES[note["template"]].format(**note["slots"]) == note["text"]


def test_the_same_seed_draws_the_same_background(drawn: Path, tmp_path: Path) -> None:
    again = tmp_path / "again"
    build_book(SEED, again, tmp_path, background=True, background_archetypes=frozenset({10}))
    drawn_files = json.loads((drawn / "manifest.json").read_text())["files"]
    again_files = json.loads((again / "manifest.json").read_text())["files"]
    # Each archetype's pairs are drawn from their own stream, so drawing one archetype again gives
    # the same files as it has in the whole draw.
    assert again_files and all(
        drawn_files[name] == digest for name, digest in again_files.items() if name.startswith("households/")
    )


def test_a_seeded_crossing_in_a_background_household_fails_the_thresholds_check(drawn: Path, tmp_path: Path) -> None:
    book = tmp_path / "book"
    shutil.copytree(drawn, book)
    sealed = json.loads((book / "sealed" / "households.json").read_text())["households"]
    household = book / "households" / sealed[0]["household_id"]
    ips = household / "portfolio" / "ips.json"
    data = json.loads(ips.read_text())
    data["concentration_limit"]["share_of_household"] = "0.05"
    ips.write_text(json.dumps(data))
    line = next(
        line
        for line in check_book(book).lines
        if line.household_id == sealed[0]["household_id"] and line.check == "background thresholds"
    )
    assert not line.passed
    assert any("crosses a concentration threshold with no registry entry" in p for p in line.problems)


PRIVATE = Path(os.environ.get("CASEBOOK_PRIVATE", "/nonexistent"))


@pytest.mark.skipif(not (PRIVATE / "book" / "scripted").is_dir(), reason="the held-out pairs live in $CASEBOOK_PRIVATE")
def test_the_whole_book_is_100_households_and_900_passing_lines(tmp_path: Path) -> None:
    # Slice 6, with the four held-out households added back: built outside the repo, as the gate demands.
    out = tmp_path / "whole"
    result = build_book(SEED, out, SCRIPTS, held_out=True, background=True, extra_scripts=PRIVATE / "book" / "scripted")
    assert len(result.households) == 100
    report = check_book(out)
    assert report.passed and len(report.lines) == 900
    # Slice 7 on all 100: a composite 1099 each, and a tax summary each whose every figure agrees.
    for household in result.households:
        index = json.loads((out / "households" / household / "documents" / "index.json").read_text())["documents"]
        assert any(entry["kind"] == "form_1099_composite" for entry in index), household
        summary = json.loads((out / "sealed" / household / "tax_summary.json").read_text())
        assert summary["summaries"] and all(c["agrees"] for c in summary["comparisons"]), household


def sealed_households(book: Path) -> list[dict[str, Any]]:
    return json.loads((book / "sealed" / "households.json").read_text())["households"]


@pytest.mark.parametrize("archetype", [5, 7])
def test_without_their_entries_the_drawn_rmd_traps_cross_the_rmd_threshold(
    full_book: Path, monkeypatch: pytest.MonkeyPatch, archetype: int
) -> None:
    # Reviewers A and B, slice 6 round 1: the check looked at traditional IRAs only, so a 401(k)'s
    # missed RMD (archetype 5) and an inherited IRA's (archetype 7) passed with their entries removed.
    def unregistered(*_args: Any, **_kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(thresholds, "registered", unregistered)
    traps = [
        h["household_id"]
        for h in sealed_households(full_book)
        if h["archetype"] == archetype and h["role"] == "trap" and h["set"] == "background"
    ]
    assert len(traps) == 4
    for household in traps:
        problems = thresholds.check_thresholds(full_book / "households" / household)
        kind = "a 401(k)" if archetype == 5 else "an inherited IRA"
        assert any(kind in p and "owes" in p for p in problems), (household, problems)


def test_a_401k_payment_does_not_meet_the_owners_ira_rmds(full_book: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Reviewers A and B: aggregation credited any account's payment toward the owner's IRAs.
    twin = next(
        h["household_id"]
        for h in sealed_households(full_book)
        if h["archetype"] == 5 and h["role"] == "twin" and h["set"] == "background"
    )
    root = full_book / "households" / twin
    kinds = {a["account_id"]: a["account_type"] for a in read_csv(root, ACCOUNTS_CSV, ACCOUNTS_COLUMNS)}
    kept = [
        t
        for t in read_transactions(root)
        if not (t.type == "DISTRIBUTION" and kinds[t.account_id] == "traditional_ira")
    ]
    assert any(t.type == "DISTRIBUTION" and kinds[t.account_id] == "401k" for t in kept)

    def without_ira_payments(_root: Path) -> list[TransactionRow]:
        return kept

    monkeypatch.setattr(thresholds, "read_transactions", without_ira_payments)
    unpaid = [a for a, k in kinds.items() if k == "traditional_ira"]
    problems = thresholds.check_thresholds(root)
    assert all(any(f"{a} owes a 2025 distribution" in p for p in problems) for a in unpaid), problems


@pytest.mark.parametrize(
    ("born", "beginning"),
    [
        # Worked by hand: 70½ on 2016-08-11, so 1 April 2017; 72 in 2021; 73 in 2026; 75 in 2035.
        (date(1946, 2, 11), date(2017, 4, 1)),
        (date(1948, 7, 1), date(2020, 4, 1)),
        (date(1949, 9, 1), date(2022, 4, 1)),
        (date(1953, 4, 3), date(2027, 4, 1)),
        (date(1960, 1, 1), date(2036, 4, 1)),
    ],
)
def test_the_checks_required_beginning_date(born: date, beginning: date) -> None:
    assert thresholds.required_beginning(born) == beginning


def test_no_annual_review_seats_a_person_after_their_death(full_book: Path) -> None:
    # Reviewers A and B, slice 6 round 1: a clean twin's annual review seated a spouse who had died.
    # Only who attends is checked; a later note may well speak of the death (round 2's note).
    reviews = 0
    for crm_file in sorted((full_book / "households").glob("*/crm/crm.json")):
        crm = json.loads(crm_file.read_text())
        dead = {c["name"]: c["died"] for c in crm["contacts"] if c.get("died")}
        for note in crm["notes"]:
            if note.get("template") != "annual_review":
                continue
            reviews += 1
            late = [name for name, died in dead.items() if name in note["slots"]["parties"] and note["date"] > died]
            assert late == [], (crm_file.parent.parent.name, note["note_id"], late)
    assert reviews == 96
