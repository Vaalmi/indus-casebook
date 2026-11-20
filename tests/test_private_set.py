"""docs/PLAN.md, slice 11: the private set stays private. The runner loads a private task only from
`$CASEBOOK_PRIVATE` and keeps its key and unmapped record there; the public repo's check, and the site build
the release workflow runs, fail on a private task, a private key, a private run's folder or record, or a line
of a private file, copied in."""

import io
import json
import os
import shutil
import zipfile
from pathlib import Path

import pytest

from casebook.cli import main
from casebook.graders.registry import GRADERS
from casebook.model.ledger import is_private_task_id
from casebook.publish.private_set import (
    FINGERPRINTS,
    SharedTextError,
    fingerprints,
    private_households,
    private_set_problems,
)
from casebook.publish.site_build import SiteBuildError, build_site
from casebook.publish.zips import write_zip
from casebook.runner.run import private_root
from casebook.runner.session import PrivateTaskError, refuse_private_pairs
from casebook.tasks.matrix import load_matrix
from casebook.tasks.task import load_task

from .conftest import README, ROOT, StandIn
from .test_run_session import answer_for

TASKS = ROOT / "tasks" / "public"
# A private task's ID, built so that no public file states one.
PRIVATE_ID = "X-" + "REC-09"


def private_task(folder: Path) -> Path:
    """A private task: T-REC-01's file under a private ID, with a line no public task has."""
    folder.mkdir(parents=True, exist_ok=True)
    text = (TASKS / "T-REC-01.toml").read_text().replace('task_id = "T-REC-01"', f'task_id = "{PRIVATE_ID}"')
    text = text.replace("The advisor asks:", "The advisor, back from the review with the Okonkwo trustees, asks:")
    path = folder / f"{PRIVATE_ID}.toml"
    path.write_text(text)
    return path


def test_the_public_repo_holds_nothing_of_the_private_set() -> None:
    assert private_set_problems(ROOT, repository=True) == []


def test_a_private_id_has_its_own_shape() -> None:
    assert is_private_task_id(PRIVATE_ID) and not is_private_task_id("T-REC-01")
    assert not is_private_task_id("X-1") and not is_private_task_id(PRIVATE_ID + "9")


@pytest.fixture
def private_folder(tmp_path: Path) -> Path:
    """A private folder with one task file, one key and one test, and the public tree's fingerprints of it."""
    private = tmp_path / "private"
    private_task(private / "tasks")
    (private / "keys" / "0.0.1").mkdir(parents=True)
    (private / "keys" / "0.0.1" / f"{PRIVATE_ID}.json").write_text('{"finding": "fee_error", "debited": "1234.56"}\n')
    return private


def public_tree(tmp_path: Path, private: Path) -> tuple[Path, Path]:
    """A copy of the public tasks and docs, and the private folder's fingerprints taken against it."""
    public = tmp_path / "public"
    shutil.copytree(TASKS, public / "tasks" / "public")
    shutil.copytree(ROOT / "docs", public / "docs")
    prints = tmp_path / "fingerprints.json"
    # The private task shares the public tasks' voice; that boilerplate is approved as shared.
    prints.write_text(json.dumps(fingerprints(private, public, previous=None, approve_shared=True)))
    return public, prints


def test_a_copied_private_task_file_is_found(tmp_path: Path, private_folder: Path) -> None:
    public, prints = public_tree(tmp_path, private_folder)
    assert private_set_problems(public, prints) == []
    shutil.copy(private_folder / "tasks" / f"{PRIVATE_ID}.toml", public / "tasks" / "public" / "renamed.toml")
    problems = private_set_problems(public, prints)
    assert any("a copy of a private file" in p for p in problems), problems
    assert any(f"it is private task {PRIVATE_ID}'s" in p for p in problems), problems


def test_a_copied_private_key_is_found_under_any_name(tmp_path: Path, private_folder: Path) -> None:
    public, prints = public_tree(tmp_path, private_folder)
    key = private_folder / "keys" / "0.0.1" / f"{PRIVATE_ID}.json"
    shutil.copy(key, public / "docs" / f"{PRIVATE_ID}.json")
    shutil.copy(key, public / "docs" / "answer.json")
    problems = private_set_problems(public, prints)
    assert f"docs/{PRIVATE_ID}.json: its path names private task {PRIVATE_ID}" in problems
    assert "docs/answer.json: a copy of a private file" in problems


def test_a_private_task_packed_in_an_archive_is_found(tmp_path: Path, private_folder: Path) -> None:
    """Whole-branch review, reviewer A: a private task in a zip committed to the repo passed its check."""
    public, prints = public_tree(tmp_path, private_folder)
    task = (private_folder / "tasks" / f"{PRIVATE_ID}.toml").read_bytes()
    inner = write_zip({"task.toml": task})
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:  # compressed: no line of it shows as it is
        archive.writestr("notes.md", "nothing\n")
        archive.writestr("old/inner.zip", inner)
    (public / "docs" / "backup.zip").write_bytes(packed.getvalue())
    (public / "docs" / "backup.tar.gz").write_bytes(b"not read")
    problems = private_set_problems(public, prints)
    assert "docs/backup.zip!old/inner.zip!task.toml: a copy of a private file" in problems
    assert f"docs/backup.zip!old/inner.zip!task.toml: it is private task {PRIVATE_ID}'s (its task_id)" in problems
    assert "docs/backup.tar.gz: an archive the gate cannot read; unpack it or leave it out" in problems
    assert not any(p.startswith("docs/backup.zip:") for p in problems), problems


def test_a_private_run_s_folder_and_record_are_found(tmp_path: Path, private_folder: Path) -> None:
    """A private task's fixtures are its background pair's public files, filtered by its cutoff; the run that
    holds them is the task's, and says so by its folder's name and its record's task_id."""
    public, prints = public_tree(tmp_path, private_folder)
    run = public / "published" / "runs" / "copied"
    (run / "workspace-1" / "crm").mkdir(parents=True)
    (run / "workspace-1" / "crm" / "crm.json").write_text("{}")
    (run / "record.json").write_text(json.dumps({"run_id": "r", "task_id": PRIVATE_ID, "output": "x"}))
    (public / "published" / f"{PRIVATE_ID}-skill-20261117T000000Z-0000").mkdir()
    (public / "published" / f"{PRIVATE_ID}-skill-20261117T000000Z-0000" / "attempt-1.jsonl").write_text("{}\n")
    problems = private_set_problems(public, prints)
    assert any("record.json: it is private task" in p for p in problems), problems
    assert any("attempt-1.jsonl: its path names private task" in p for p in problems), problems


def test_a_private_line_pasted_into_a_public_file_is_found(tmp_path: Path, private_folder: Path) -> None:
    public, prints = public_tree(tmp_path, private_folder)
    readme = public / "docs" / "notes.md"
    # A sentence every task shares is not private, so it is not found ...
    shared = next(line for line in (TASKS / "T-REC-01.toml").read_text().splitlines() if len(line) > 60)
    readme.write_text(shared + "\n")
    assert private_set_problems(public, prints) == []
    # ... but the private task's own line is.
    readme.write_text("The advisor, back from the review with the Okonkwo trustees, asks: anything?\n")
    assert private_set_problems(public, prints) == []  # a different line
    private_line = next(
        line for line in (private_folder / "tasks" / f"{PRIVATE_ID}.toml").read_text().splitlines() if "Okonkwo" in line
    )
    readme.write_text("Notes.\n" + private_line + "\n")
    assert any("a line of a private file" in p for p in private_set_problems(public, prints))


def test_the_site_refuses_a_private_run(book: Path, tmp_path: Path) -> None:
    from .test_held_verdicts import a_graded_record, runs_with

    record = a_graded_record("T-REC-05") | {"task_id": PRIVATE_ID, "run_id": f"{PRIVATE_ID}-skill-x"}
    runs = runs_with(tmp_path, record)
    with pytest.raises(SiteBuildError, match="private task"):
        build_site(book, tmp_path / "site", README, runs, TASKS, None)


def test_a_private_task_runs_from_the_private_folder_and_publishes_nothing(
    tmp_path: Path, real_book: Path, standin_cli: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    standin_cli.answer.write_text(answer_for(real_book))
    private_task(private_root() / "tasks")
    published = tmp_path / "published"
    paths = ["--keys", str(published / "keys"), "--runs", str(published / "runs")]
    assert main(["run", "--task", PRIVATE_ID, "--arm", "basic", "--book", str(real_book), *paths]) == 0
    assert ", score 100" in capsys.readouterr().out
    assert not published.exists()
    assert (private_root() / "keys" / "0.0.1" / f"{PRIVATE_ID}.json").is_file()
    [record] = [json.loads(p.read_text()) for p in (private_root() / "runs").glob("*/record.json")]
    # Unmapped: the run read real tickers, and the record keeps them.
    assert record["task_id"] == PRIVATE_ID and record["state"] == "graded" and record["dataset"]["real_tickers"]


@pytest.mark.parametrize("where", ["public", "private"])
def test_a_task_in_the_wrong_folder_is_refused(
    tmp_path: Path, real_book: Path, standin_cli: StandIn, capsys: pytest.CaptureFixture[str], where: str
) -> None:
    if where == "public":  # a private task copied into a public folder
        tasks, task_id = tmp_path / "tasks", PRIVATE_ID
        private_task(tasks)
    else:  # a public task copied into the private folder
        tasks, task_id = private_root() / "tasks", "T-REC-01"
        tasks.mkdir(parents=True)
        shutil.copy(TASKS / "T-REC-01.toml", tasks)
    args = ["run", "--task", task_id, "--arm", "basic", "--book", str(real_book), "--tasks", str(tasks)]
    assert main([*args, "--runs", str(tmp_path / "runs"), "--keys", str(tmp_path / "keys")]) == 2
    assert "PrivateTaskError" in capsys.readouterr().err
    assert not (tmp_path / "runs").exists()


PRIVATE = Path(os.environ.get("CASEBOOK_PRIVATE", "/nonexistent"))
HAS_PRIVATE = (PRIVATE / "tasks").is_dir() and any((PRIVATE / "tasks").glob("X-*.toml"))


@pytest.mark.skipif(not HAS_PRIVATE, reason="the private set lives in $CASEBOOK_PRIVATE, absent here")
def test_the_private_tasks_are_the_private_matrix_s_and_graded() -> None:
    matrix = load_matrix(PRIVATE / "tasks" / "matrix.toml")
    tasks = {t.task_id: t for t in map(load_task, sorted((PRIVATE / "tasks").glob("X-*.toml")))}
    assert sorted(tasks) == sorted(p.task_id for p in matrix.placements)
    for task_id, task in tasks.items():
        assert is_private_task_id(task_id) and task.grader in GRADERS, task_id


@pytest.mark.skipif(not HAS_PRIVATE, reason="the private set lives in $CASEBOOK_PRIVATE, absent here")
def test_the_committed_fingerprints_cover_the_private_set_today() -> None:
    """`uv run casebook fingerprint-private` adds to them after any change to the private set: every private
    file and line, the salt, and every file of the private pairs' builds is fingerprinted."""
    committed = json.loads(FINGERPRINTS.read_text())
    builds = [PRIVATE / "out" / kind / "0.0.1" / "households" for kind in ("book", "real")]
    pair_files = [
        p for b in builds for h in sorted(private_households()) for p in sorted((b / h).rglob("*")) if p.is_file()
    ]
    assert pair_files
    public_builds = [
        p
        for b in (ROOT / "out" / "book" / "0.0.1", ROOT / "out" / "real" / "0.0.1")
        for p in sorted(b.rglob("*"))
        if p.is_file()
    ]
    # Regenerating changes nothing, and finds no private text in the repo that is not approved as shared.
    assert fingerprints(PRIVATE, ROOT, pair_files, public_builds=public_builds) == committed


def a_private_household() -> str:
    """One household of a private pair, from the public ledger (no public file states one)."""
    return sorted(private_households())[0]


def test_the_ledger_keeps_the_eight_private_pair_households() -> None:
    assert len(private_households()) == 8


def test_a_private_pair_household_s_files_are_found_wherever_copied(tmp_path: Path, private_folder: Path) -> None:
    """A private task's fixtures are its household's files: each copy is found by its path or its household_id."""
    public, prints = public_tree(tmp_path, private_folder)
    household = a_private_household()
    crm = public / "docs" / "workspace" / "crm"
    crm.mkdir(parents=True)
    (crm / "crm.json").write_text(json.dumps({"household_id": household, "notes": []}))
    (public / "docs" / "households" / household).mkdir(parents=True)
    (public / "docs" / "households" / household / "accounts.csv").write_text("account_id\nSYN-00000001\n")
    (public / "docs" / "rows.csv").write_text(f"household_id,amount\n{household},1.00\n")
    problems = private_set_problems(public, prints)
    assert (
        f"docs/workspace/crm/crm.json: it is private pair household {household}'s (its household or accounts)"
        in problems
    )
    assert any(p.startswith(f"docs/households/{household}/accounts.csv: its path names") for p in problems), problems
    assert f"docs/rows.csv: it is private pair household {household}'s (its household or accounts)" in problems


def test_a_listing_that_names_a_private_household_is_not_its_file(tmp_path: Path, private_folder: Path) -> None:
    """The ledger, and a transcript of a run that listed the CRM's households, name the IDs; neither is a
    household's file."""
    public, prints = public_tree(tmp_path, private_folder)
    household = a_private_household()
    listing = {"type": "user", "content": [{"household_id": household, "name": "A. Client"}]}
    (public / "docs" / "run.transcript.jsonl").write_text(json.dumps(listing) + "\n")
    (public / "docs" / "notes.md").write_text(f"The ledger keeps {household}.\n")
    assert private_set_problems(public, prints) == []


def test_a_public_task_never_runs_on_a_book_with_a_private_pair(book: Path, book_copy: Path) -> None:
    """Reviewers A and B, slice 11 round 1: T-REC-05 run on the private build wrote its private households'
    figures into a public key. It is refused before any key is computed."""
    manifest = json.loads((book_copy / "manifest.json").read_text())
    manifest["households"].append({**manifest["households"][0], "household_id": a_private_household()})
    (book_copy / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(PrivateTaskError, match="holds the private pair households"):
        refuse_private_pairs(load_task(TASKS / "T-REC-05.toml"), book_copy)
    refuse_private_pairs(load_task(TASKS / "T-REC-05.toml"), book)  # the public build is fine


def test_a_private_pair_s_custodian_file_is_found_by_its_accounts(tmp_path: Path, private_folder: Path) -> None:
    """Reviewers A and B, slice 11 round 1: a custodian CSV names accounts, not households, and escaped."""
    public, prints = public_tree(tmp_path, private_folder)
    account = "SYN-" + a_private_household().removeprefix("HH-") + "0002"
    (public / "docs" / "positions.csv").write_text(f"account_id,security_id,units\n{account},SEC-0001,10\n")
    (public / "docs" / "public.csv").write_text("account_id,security_id,units\nSYN-12040002,SEC-0001,10\n")
    problems = private_set_problems(public, prints)
    assert problems == [
        f"docs/positions.csv: it is private pair household {a_private_household()}'s (its household or accounts)"
    ]


@pytest.mark.parametrize("folder", ["out", "node_modules", ".git", "__pycache__", "review"])
def test_a_release_s_files_are_scanned_whole(tmp_path: Path, private_folder: Path, folder: str) -> None:
    """Reviewers A and B, slice 11 round 1: the repo's tool and cache folders were skipped at any depth, in a
    release too, so a private file nested in one went into the site unscanned."""
    public, prints = public_tree(tmp_path, private_folder)
    nested = public / "published" / "runs" / folder
    nested.mkdir(parents=True)
    shutil.copy(private_folder / "tasks" / f"{PRIVATE_ID}.toml", nested / "copy.toml")
    assert any(p.startswith(f"published/runs/{folder}/copy.toml") for p in private_set_problems(public, prints))
    # The repo's own scan still skips them (a build in out/, a virtual environment).
    assert not any(f"/{folder}/" in p for p in private_set_problems(public, prints, repository=True))


def test_regenerating_over_a_copied_private_line_is_refused_and_keeps_it(tmp_path: Path, private_folder: Path) -> None:
    """Reviewers A and B, slice 11 round 1: regenerating over a leak dropped the leaked line, as shared text."""
    public, prints = public_tree(tmp_path, private_folder)
    private_line = next(
        line for line in (private_folder / "tasks" / f"{PRIVATE_ID}.toml").read_text().splitlines() if "Okonkwo" in line
    )
    (public / "docs" / "notes.md").write_text(private_line + "\n")
    assert any("a line of a private file" in p for p in private_set_problems(public, prints))
    with pytest.raises(SharedTextError, match=r"docs/notes\.md"):
        fingerprints(private_folder, public, previous=prints)
    # Approved by mistake, it is still found: a fingerprint once taken is kept.
    again = tmp_path / "again.json"
    again.write_text(json.dumps(fingerprints(private_folder, public, previous=prints, approve_shared=True)))
    assert any("a line of a private file" in p for p in private_set_problems(public, again))


def test_a_new_private_file_copied_out_before_its_fingerprint_is_refused(tmp_path: Path, private_folder: Path) -> None:
    """Reviewers A and B, slice 11 round 2: a private file written after the last fingerprints, and copied into
    the public tree before the next, was taken for shared text and never fingerprinted."""
    public, prints = public_tree(tmp_path, private_folder)
    edited = private_folder / "tasks" / f"{PRIVATE_ID}.toml"
    edited.write_text(edited.read_text().replace("Okonkwo trustees", "Okonkwo trustees and their lawyer"))
    shutil.copy(edited, public / "docs" / "task-example.md")
    assert private_set_problems(public, prints) == []  # the old fingerprints cannot know it
    with pytest.raises(SharedTextError) as refused:
        fingerprints(private_folder, public, previous=prints)
    assert any(o.startswith("docs/task-example.md is private file tasks/") for o in refused.value.overlaps)
    assert any("is a line of tasks/" in o and "Okonkwo" in o for o in refused.value.overlaps)


def test_fingerprinting_over_a_leak_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import casebook.publish.private_set as private_set

    monkeypatch.setenv("CASEBOOK_PRIVATE", str(ROOT.parent / "casebook-private-test-unused"))

    def leaking(*_args: object, **_kwargs: object) -> list[str]:
        return ["docs/x.md: a line of a private file"]

    monkeypatch.setattr(private_set, "private_set_problems", leaking)
    assert main(["fingerprint-private"]) == 1
    assert "holds the private set already" in capsys.readouterr().err


def test_a_copied_salt_is_found_under_any_name(tmp_path: Path, private_folder: Path) -> None:
    """Reviewer A, slice 11 round 1: the salt lets anyone draw the private pairs; a copy was not found."""
    (private_folder / "book").mkdir()
    (private_folder / "book" / "private_salt").write_text("ab" * 32 + "\n")
    public, prints = public_tree(tmp_path, private_folder)
    (public / "book").mkdir()
    shutil.copy(private_folder / "book" / "private_salt", public / "book" / "private_salt")
    (public / "docs" / "seed.txt").write_text("salt: " + "ab" * 32 + "\n")
    (public / "docs" / "only.txt").write_text("ab" * 32 + "\n")
    problems = private_set_problems(public, prints)
    assert "book/private_salt: a copy of a private file" in problems
    assert any(p.startswith("docs/only.txt: a line of a private file") for p in problems), problems


def test_a_private_file_a_public_build_also_has_is_not_fingerprinted(
    tmp_path: Path, private_folder: Path, book: Path
) -> None:
    """A private household's header-only CSV is byte for byte a public household's; fingerprinting it refused
    every public site (found building slice 11's second round)."""
    header = next(p for p in sorted(book.rglob("*.csv")) if len(p.read_text().splitlines()) == 1)
    (private_folder / "keys" / "0.0.1" / "copy.csv").write_bytes(header.read_bytes())
    public = tmp_path / "public"
    (public / "docs").mkdir(parents=True)
    shutil.copy(header, public / "docs" / "header.csv")
    unaware = tmp_path / "unaware.json"
    unaware.write_text(json.dumps(fingerprints(private_folder, public / "empty", previous=None)))
    assert "docs/header.csv: a copy of a private file" in private_set_problems(public, unaware)
    aware = tmp_path / "aware.json"
    aware.write_text(json.dumps(fingerprints(private_folder, public / "empty", previous=None, public_builds=[header])))
    assert private_set_problems(public, aware) == []
