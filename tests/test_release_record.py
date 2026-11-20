"""Slice 16: the stable-ID record. "A changed household or task ID with no new version and errata entry fails the
release" (docs/PLAN.md, slice 16); docs/SPEC.md, Rules: "Stable IDs: a published household or task ID never
changes meaning. Corrections ship as a new version with an errata entry"."""

import dataclasses
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from casebook.graders.registry import GRADERS
from casebook.model.ledger import parse_ledger
from casebook.notice import NOTICE
from casebook.publish.release_record import (
    RELEASES,
    Release,
    ReleaseRecordError,
    id_digests,
    load_releases,
    record_release,
    stable_id_problems,
)
from casebook.site.errata import Correction

from .conftest import FEATURED, ROOT

TASKS = ROOT / "tasks" / "public"
# The 24 public tasks in tasks/public, six per workflow.
PUBLIC_TASKS = sorted(f"T-{w}-0{n}" for w in ("CMP", "MTG", "REC", "TAX") for n in range(1, 7))

A, B, C, D = ("a" * 64), ("b" * 64), ("c" * 64), ("d" * 64)
LEDGER = parse_ledger(
    {
        "households": {
            "HH-4821": {"archetype": 10, "pair": 1, "role": "trap"},
            "HH-7350": {"archetype": 10, "pair": 1, "role": "twin"},
            "HH-1204": {"archetype": 1, "pair": 1, "role": "trap"},
        },
        "tasks": {"T-REC-01": {"household_id": "HH-4821", "workflow": "reconciliation"}},
    },
    "test ledger",
)
FIRST = {"households": {"HH-4821": A, "HH-7350": B}, "tasks": {"T-REC-01": C}}
V010 = Release("v0.1.0", "0.0.1", date(2026, 11, 19), FIRST)


def changed(kind: str, id_: str, digest: str, ids: dict[str, dict[str, str]] = FIRST) -> dict[str, dict[str, str]]:
    return {k: {**v, id_: digest} if k == kind else dict(v) for k, v in ids.items()}


def fix(version: str, *ids: str) -> Correction:
    return Correction(version, date(2026, 12, 1), "A hand-written correction.", ids)


# The clean cases.


def test_a_first_release_passes() -> None:
    assert stable_id_problems(FIRST, "0.0.1", [], [], LEDGER) == []


def test_the_same_ids_again_under_the_same_book_version_pass() -> None:
    """A second tag (a package fix, say) shipping the same book is no correction."""
    assert stable_id_problems(FIRST, "0.0.1", [V010], [], LEDGER) == []


def test_a_correction_under_a_new_version_with_an_errata_entry_naming_the_id_passes() -> None:
    current = changed("households", "HH-4821", D)
    assert stable_id_problems(current, "0.0.2", [V010], [fix("0.0.2", "HH-4821")], LEDGER) == []


def test_an_errata_entry_for_an_unreleased_version_between_counts() -> None:
    """0.0.2 was corrected but never tagged; 0.0.3 ships its correction."""
    current = changed("tasks", "T-REC-01", D)
    assert stable_id_problems(current, "0.0.3", [V010], [fix("0.0.2", "T-REC-01")], LEDGER) == []


def test_a_new_id_under_a_new_version_needs_no_errata_entry() -> None:
    current = changed("households", "HH-1204", D)
    assert stable_id_problems(current, "0.0.2", [V010], [], LEDGER) == []


# The refusals.


@pytest.mark.parametrize(("kind", "id_"), [("households", "HH-4821"), ("tasks", "T-REC-01")])
def test_a_changed_id_under_the_released_book_version_fails(kind: str, id_: str) -> None:
    problems = stable_id_problems(changed(kind, id_, D), "0.0.1", [V010], [fix("0.0.1", id_)], LEDGER)
    assert len(problems) == 1 and problems[0].startswith(f"{id_} changed under book version 0.0.1")


def test_a_new_id_under_the_released_book_version_fails() -> None:
    problems = stable_id_problems(changed("households", "HH-1204", D), "0.0.1", [V010], [], LEDGER)
    assert problems == ["HH-1204 is new under book version 0.0.1, which v0.1.0 released"]


@pytest.mark.parametrize(
    "errata",
    [
        [],
        [fix("0.0.2", "HH-7350")],  # names another ID
        [fix("0.0.1", "HH-4821")],  # names it, for the version already released
        [fix("0.0.3", "HH-4821")],  # names it, for a version after this one
    ],
    ids=["no entry", "another id", "the released version", "a later version"],
)
def test_a_changed_id_under_a_new_version_without_an_errata_entry_naming_it_fails(errata: list[Correction]) -> None:
    problems = stable_id_problems(changed("households", "HH-4821", D), "0.0.2", [V010], errata, LEDGER)
    assert len(problems) == 1 and problems[0].startswith("HH-4821 changed since v0.1.0 (book 0.0.1)")


def test_a_released_id_now_missing_fails() -> None:
    current = {"households": {"HH-4821": A}, "tasks": {"T-REC-01": C}}
    problems = stable_id_problems(current, "0.0.2", [V010], [fix("0.0.2", "HH-7350")], LEDGER)
    assert problems == ["HH-7350 was released and is missing"]


def test_an_id_released_before_the_last_release_and_now_missing_fails() -> None:
    later = Release("v0.1.1", "0.0.2", date(2026, 12, 1), {"households": {"HH-4821": A}, "tasks": {"T-REC-01": C}})
    current = {"households": {"HH-4821": A}, "tasks": {"T-REC-01": C}}
    assert stable_id_problems(current, "0.0.2", [V010, later], [], LEDGER) == ["HH-7350 was released and is missing"]


def test_an_id_not_in_the_id_ledger_fails() -> None:
    current = changed("tasks", "T-REC-09", D, changed("households", "HH-0001", D))
    assert stable_id_problems(current, "0.0.1", [], [], LEDGER) == [
        "HH-0001 is not in the ID ledger",
        "T-REC-09 is not in the ID ledger",
    ]


def test_a_book_version_older_than_the_last_release_fails() -> None:
    later = dataclasses.replace(V010, tag="v0.1.1", book_version="0.0.10")
    problems = stable_id_problems(FIRST, "0.0.9", [V010, later], [], LEDGER)
    assert problems == ["book version 0.0.9 is older than v0.1.1's, 0.0.10"]


# The record.


@pytest.fixture
def record(tmp_path: Path) -> Path:
    path = tmp_path / "releases.json"
    path.write_text(json.dumps({"notice": NOTICE, "releases": []}))
    return path


def test_the_published_record_holds_no_release_yet_and_carries_the_notice() -> None:
    assert load_releases(RELEASES) == []
    assert json.loads(RELEASES.read_text())["notice"] == NOTICE


def test_recording_a_release_adds_its_entry(record: Path) -> None:
    record_release("v0.1.0", "0.0.1", date(2026, 11, 19), FIRST, [], LEDGER, record)
    assert json.loads(record.read_text()) == {
        "notice": NOTICE,
        "releases": [{"tag": "v0.1.0", "book_version": "0.0.1", "date": "2026-11-19", "ids": FIRST}],
    }
    assert load_releases(record) == [V010]


def test_recording_the_same_tag_with_the_same_ids_again_changes_nothing(record: Path) -> None:
    record_release("v0.1.0", "0.0.1", date(2026, 11, 19), FIRST, [], LEDGER, record)
    before = record.read_bytes()
    assert record_release("v0.1.0", "0.0.1", date(2026, 11, 20), FIRST, [], LEDGER, record) == V010
    assert record.read_bytes() == before


@pytest.mark.parametrize(
    ("book_version", "ids"),
    [("0.0.1", changed("tasks", "T-REC-01", D)), ("0.0.2", FIRST)],
    ids=["other digests", "another book version"],
)
def test_a_tag_already_recorded_with_other_digests_is_refused(
    record: Path, book_version: str, ids: dict[str, dict[str, str]]
) -> None:
    record_release("v0.1.0", "0.0.1", date(2026, 11, 19), FIRST, [], LEDGER, record)
    before = record.read_bytes()
    with pytest.raises(ReleaseRecordError, match=r"v0\.1\.0 is already recorded"):
        record_release("v0.1.0", book_version, date(2026, 11, 19), ids, [fix(book_version, "T-REC-01")], LEDGER, record)
    assert record.read_bytes() == before


def test_a_release_that_fails_the_stable_id_rule_is_not_recorded(record: Path) -> None:
    record_release("v0.1.0", "0.0.1", date(2026, 11, 19), FIRST, [], LEDGER, record)
    before = record.read_bytes()
    current = changed("households", "HH-4821", D)
    with pytest.raises(ReleaseRecordError, match=r"HH-4821 changed since v0\.1\.0"):
        record_release("v0.1.1", "0.0.2", date(2026, 12, 1), current, [], LEDGER, record)
    assert record.read_bytes() == before
    record_release("v0.1.1", "0.0.2", date(2026, 12, 1), current, [fix("0.0.2", "HH-4821")], LEDGER, record)
    assert [r.tag for r in load_releases(record)] == ["v0.1.0", "v0.1.1"]


@pytest.mark.parametrize(
    "data",
    [
        {"releases": []},
        {"notice": "UNVALIDATED SYNTHETIC RESEARCH PREVIEW.", "releases": []},
        {"notice": NOTICE, "releases": [V010.to_dict(), V010.to_dict()]},
        {"notice": NOTICE, "releases": [dataclasses.replace(V010, book_version="0.0.2").to_dict(), V010.to_dict()]},
        {"notice": NOTICE, "releases": [{**V010.to_dict(), "tag": "0.1.0"}]},
        {"notice": NOTICE, "releases": [{**V010.to_dict(), "ids": {"households": {"HH-4821": "x"}, "tasks": {}}}]},
        {"notice": NOTICE, "releases": [{**V010.to_dict(), "date": "19 November"}]},
    ],
    ids=["no notice", "not the notice", "a tag twice", "versions back", "a bad tag", "a bad digest", "a bad date"],
)
def test_a_malformed_record_is_refused(record: Path, data: object) -> None:
    record.write_text(json.dumps(data))
    with pytest.raises(ReleaseRecordError):
        load_releases(record)


# The digests, on the featured book.


def test_id_digests_cover_each_household_s_files_and_each_task_s_file_and_grader(
    book: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    digests = id_digests(book, TASKS)
    assert sorted(digests["households"]) == sorted(FEATURED)
    assert sorted(digests["tasks"]) == PUBLIC_TASKS
    assert len({*digests["households"].values(), *digests["tasks"].values()}) == len(FEATURED) + len(PUBLIC_TASKS)
    assert id_digests(book, TASKS) == digests

    # The digests read the manifest and the two sealed files the book shares: a copy of the manifest with one hash
    # changed stands for a changed file.
    manifest = json.loads((book / "manifest.json").read_text())
    copy = tmp_path / "book"
    (copy / "sealed").mkdir(parents=True)
    for shared in ("sealed/registry.json", "sealed/households.json"):
        shutil.copyfile(book / shared, copy / shared)

    def households_after(path: str) -> set[str]:
        files = {**manifest["files"], path: "0" * 64}
        (copy / "manifest.json").write_text(json.dumps({**manifest, "files": files}))
        after = id_digests(copy, TASKS)["households"]
        return {h for h in after if after[h] != digests["households"][h]}

    assert households_after("households/HH-4821/custodian/positions.csv") == {"HH-4821"}
    assert households_after("sealed/HH-4821/tax_summary.json") == {"HH-4821"}
    assert households_after("securities/securities.csv") == set()
    assert households_after("sealed/registry.json") == set()

    def households_after_editing(shared: str, key: str, field: str, value: object) -> set[str]:
        data = json.loads((book / shared).read_text())
        [entry] = [e for e in data[key] if e["household_id"] == "HH-4821"]
        entry[field] = value
        (copy / shared).write_text(json.dumps(data))
        (copy / "manifest.json").write_text(json.dumps(manifest))
        after = id_digests(copy, TASKS)["households"]
        shutil.copyfile(book / shared, copy / shared)
        return {h for h in after if after[h] != digests["households"][h]}

    # HH-4821's planted item (one registry entry, PI-0001) and its line in the sealed household list.
    assert households_after_editing("sealed/registry.json", "entries", "title", "Another planted item") == {"HH-4821"}
    assert households_after_editing("sealed/households.json", "households", "role", "twin") == {"HH-4821"}

    tasks = tmp_path / "tasks"
    shutil.copytree(TASKS, tasks)
    with (tasks / "T-REC-01.toml").open("a") as f:
        f.write("# one more line\n")
    after = id_digests(book, tasks)["tasks"]
    assert {t for t in after if after[t] != digests["tasks"][t]} == {"T-REC-01"}

    # T-REC-01's grader is fee_reconciliation (tasks/public/T-REC-01.toml); a byte of its sources moving moves it.
    spec = GRADERS["fee_reconciliation"]
    monkeypatch.setitem(GRADERS, spec.name, dataclasses.replace(spec, sources=(*spec.sources, TASKS / "T-MTG-01.toml")))
    after = id_digests(book, TASKS)["tasks"]
    assert "T-REC-01" in {t for t in after if after[t] != digests["tasks"][t]}
    assert after["T-MTG-01"] == digests["tasks"]["T-MTG-01"]
