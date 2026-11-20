"""The one `casebook` command."""

import argparse
import json
import secrets
import sys
from collections.abc import Sequence
from pathlib import Path

from casebook import BOOK_VERSION

DEFAULT_SEED = 2026
DEFAULT_BOOK = Path("out/book") / BOOK_VERSION
REAL_BOOK = Path("out/real") / BOOK_VERSION
DEFAULT_SITE = Path("out/site")
# The sample book, committed inside the plugin so that installing the plugin from the repo ships it.
DEFAULT_SAMPLE_BOOK = Path("plugin/book")
DEFAULT_SCRIPTS = Path("book/scripted")
# Release files kept in the repo, so a tag builds the same site: mapped run records and the
# keys that may be published (docs/SPEC.md, Running it: "Run records and transcripts are kept
# as release files").
PUBLISHED_RUNS = Path("published/runs")
PUBLISHED_KEYS = Path("published/keys")
# The hand audit: its worksheet (out/, rebuilt from the book) and the owner's log (published with the preview).
DEFAULT_AUDIT = Path("out/audit")
AUDIT_LOG = Path("published/audit/audit-log.csv")
# The private salt, which draws the private pairs, inside $CASEBOOK_PRIVATE; never in the repo or a built file.
PRIVATE_SALT = Path("book") / "private_salt"


def _private_salt(private: Path) -> str:
    """The private salt, written once (a fresh random one) the first time a held-out build asks for it."""
    path = private / PRIVATE_SALT
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32) + "\n", encoding="utf-8")
        print(f"wrote a new private salt to {path}; keep it with the private set", file=sys.stderr)
    return path.read_text(encoding="utf-8").strip()


def _build(args: argparse.Namespace) -> int:
    from casebook.build import BuildError, build_book
    from casebook.generate.script import ScriptError

    out = args.out or (REAL_BOOK if args.real_tickers else DEFAULT_BOOK)
    scripts, extra, salt = args.scripts, None, None
    if args.held_out:
        from casebook.runner.run import PrivateFolderError, private_root

        try:
            private = private_root()
        except PrivateFolderError as error:
            print(f"build failed: {error}", file=sys.stderr)
            return 1
        # The whole book: the repo's scripts, the held-out pairs and the background households, the
        # private pairs drawn with the private salt.
        extra = private / DEFAULT_SCRIPTS
        out = args.out or private / out
        salt = _private_salt(private)
    try:
        result = build_book(
            args.seed,
            out,
            scripts,
            args.real_tickers,
            held_out=args.held_out,
            background=True,
            extra_scripts=extra,
            private_salt=salt,
        )
    except (BuildError, ScriptError) as error:
        print(f"build failed: {error}", file=sys.stderr)
        return 1
    print(f"built {len(result.households)} households, {result.files} files, into {result.root}")
    return 0


def _check(args: argparse.Namespace) -> int:
    from casebook.checks import check_book

    report = check_book(args.book)
    sys.stdout.write(report.render())
    return 0 if report.passed else 1


def _site(args: argparse.Namespace) -> int:
    from casebook.publish.site_build import SiteBuildError, build_site
    from casebook.site.tasks import UnnamedResultError

    try:
        pages = build_site(args.book, args.out, args.readme, args.runs, args.tasks, args.keys, errata=args.errata)
    except (SiteBuildError, UnnamedResultError) as error:
        print(f"site build failed: {error}", file=sys.stderr)
        return 1
    print(f"built {pages} pages into {args.out}")
    return 0


def _release(args: argparse.Namespace) -> int:
    from datetime import date

    from casebook.publish.release import ReleaseError, ReleaseInputs, build_release, bundle_summary
    from casebook.runner.session import HELD_KEYS

    if args.record and args.date is None:
        print("release failed: --record needs --date YYYY-MM-DD, the release's date", file=sys.stderr)
        return 1
    inputs = ReleaseInputs(book=args.book, real_book=args.real_book, repo=Path(), held_keys=HELD_KEYS)
    try:
        bundle = build_release(inputs, args.out, date.fromisoformat(args.date) if args.record else None)
    except ReleaseError as error:
        print(f"release failed: {error}", file=sys.stderr)
        return 1
    print(f"{'recorded and wrote' if args.record else 'wrote'} the preview release {bundle_summary(bundle)}")
    return 0


def _review_packet(args: argparse.Namespace) -> int:
    from casebook.publish.review_packet import ReviewPacketError, packet_zip, write_review_packet

    try:
        folder = write_review_packet(args.book, args.out)
    except ReviewPacketError as error:
        print(f"review packet failed: {error}", file=sys.stderr)
        return 1
    print(f"wrote the review packet into {folder} and {packet_zip(folder)}; it is never part of the public release")
    return 0


def _sample_book(args: argparse.Namespace) -> int:
    from casebook.publish.sample_book import SampleBookError, build_sample_book

    try:
        sample = build_sample_book(args.book, args.out)
    except SampleBookError as error:
        print(f"sample book failed: {error}", file=sys.stderr)
        return 1
    print(f"wrote the sample book: {len(sample.households)} households, {sample.files} files, into {args.out}")
    return 0


def _run(args: argparse.Namespace) -> int:
    from casebook.model.ledger import is_private_task_id
    from casebook.runner.config import SharedConfig
    from casebook.runner.preflight import RunRefusedError
    from casebook.runner.run import private_root
    from casebook.runner.session import run_and_grade

    try:
        # A private task runs on a private pair, which only the held-out real-ticker build in $CASEBOOK_PRIVATE has.
        secret = is_private_task_id(args.task)
        tasks = args.tasks or (private_root() / "tasks" if secret else Path("tasks/public"))
        book = args.book or (private_root() / REAL_BOOK if secret else REAL_BOOK)
        record = run_and_grade(args.task, args.arm, tasks, book, args.keys, args.runs, SharedConfig())
    except RunRefusedError as error:
        print(f"run refused: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    grade = record["grade"] or {}
    print(f"{record['run_id']}: {record['state']}", end="")
    print(f", {record['failure_reason']}" if record["failure_reason"] else f", score {grade.get('score')}")
    return 0 if record["state"] != "failed" else 1


def _pass(args: argparse.Namespace) -> int:
    from casebook.runner.config import SharedConfig
    from casebook.runner.full_pass import (
        REPEATS,
        Folders,
        load_pass,
        new_pass,
        run_ids,
        run_pass,
        status_lines,
        ungraded_runs,
    )
    from casebook.runner.preflight import RunRefusedError
    from casebook.runner.run import private_root

    if args.private and (args.status or args.resume):
        print("pass refused: --private starts a new pass of the private set alone", file=sys.stderr)
        return 2
    try:
        if args.status:
            print("\n".join(status_lines(load_pass(args.status))))
            return 0
        if args.resume:
            run = load_pass(args.resume)
        else:
            private = private_root()
            folders = Folders(
                tasks=args.tasks,
                private_tasks=args.private_tasks or private / "tasks",
                book=args.book,
                private_book=args.private_book or private / REAL_BOOK,
                keys=args.keys,
                runs=args.runs,
            )
            repeats = REPEATS if args.repeats is None else args.repeats
            run = new_pass(folders, repeats, SharedConfig(), private_only=args.private)
        run_pass(run, print)
    except RunRefusedError as error:
        print(f"pass refused: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    print("\n".join(status_lines(run)))
    if run.state == "complete":
        # The results page shows the private set's outcome counts beside the public runs, and nothing else of it.
        from casebook.site.results import ResultsError, write_private_outcomes

        try:
            # Counted from the private task folder the pass ran with, which --private-tasks may have named.
            folders = run.folders
            # The pass's own private runs: a private pass run again under a new freeze replaces the counts.
            runs = private_root() / "runs"
            written = write_private_outcomes(runs, folders.private_tasks, folders.runs.parent, run_ids(run))
        except ResultsError as error:
            # A private run kept completed and ungraded has no outcome to count: the counts wait for the owner
            # (reviewers A and B, slice 13 second targeted check).
            print(f"private outcome counts not written: {error}", file=sys.stderr)
            return 1
        print(f"private outcome counts: {written}")
    settled = not any(s.state == "failed" for s in run.slots) and not ungraded_runs(run)
    return 0 if run.state == "complete" and settled else 1


def _regrade(args: argparse.Namespace) -> int:
    from casebook.runner.full_pass import load_pass, run_ids
    from casebook.runner.preflight import RunRefusedError
    from casebook.runner.regrade import is_private_pass, regrade_pass
    from casebook.runner.run import private_root
    from casebook.site.results import ResultsError, write_private_outcomes

    try:
        run = load_pass(args.pass_id)
        done = regrade_pass(run, print)
    except RunRefusedError as error:
        print(f"regrade refused: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    moved = sum(r.before != r.after for r in done)
    print(f"regraded {len(done)} runs of pass {args.pass_id}; {moved} grades changed")
    if is_private_pass(run):
        # The private counts are those of the pass's runs as graded again, saying so (the owner, 19 November 2026).
        try:
            folders = run.folders
            written = write_private_outcomes(
                private_root() / "runs", folders.private_tasks, folders.runs.parent, run_ids(run)
            )
        except ResultsError as error:
            print(f"private outcome counts not written: {error}", file=sys.stderr)
            return 1
        print(f"private outcome counts: {written}")
    return 0


def _canary(args: argparse.Namespace) -> int:
    from casebook.runner.canary import run_canary
    from casebook.runner.config import SharedConfig
    from casebook.runner.run import private_root

    result = run_canary(SharedConfig(), keep=private_root() / "canary")
    print(f"canary: {'LEAKED' if result.leaked else 'no leak'}; the CLI {result.failure or 'finished cleanly'}")
    print(result.final_text)
    return 1 if result.leaked or result.failure else 0


def _fingerprint_private(args: argparse.Namespace) -> int:
    import tempfile

    from casebook.model.files import household_dir
    from casebook.publish.private_set import (
        FINGERPRINTS,
        REPO,
        SharedTextError,
        fingerprints,
        private_households,
        private_set_problems,
        tree_files,
    )
    from casebook.runner.run import PrivateFolderError, private_root
    from casebook.tasks.fixtures import load_task_fixtures
    from casebook.tasks.task import load_task

    try:
        private = private_root()
    except PrivateFolderError as error:
        print(f"fingerprints refused: {error}", file=sys.stderr)
        return 2
    leaks = private_set_problems(REPO, repository=True)
    if leaks:
        # Regenerating over a leak would fold the copied lines into the shared ones (reviewers A and B, slice 11).
        print(
            "fingerprints refused: the public repo holds the private set already:", *leaks, sep="\n  ", file=sys.stderr
        )
        return 1
    # A private household's smallest files can be byte for byte a public one's (a header-only CSV), so the
    # public books' files are compared too: they must be built.
    public_books = [DEFAULT_BOOK, REAL_BOOK]
    missing = [str(book) for book in public_books if not (book / "manifest.json").is_file()]
    if missing:
        print(f"fingerprints refused: build the public books first ({', '.join(missing)})", file=sys.stderr)
        return 2
    public_files = [path for book in public_books for path in tree_files(book)]
    # The private pairs' built files in both private builds, and each private task's fixtures at its cutoff.
    builds = [private / "out" / kind / BOOK_VERSION for kind in ("book", "real")]
    pair_files = [
        path
        for build in builds
        for household in sorted(private_households())
        if (build / household_dir(household)).is_dir()
        for path in tree_files(build / household_dir(household))
    ]
    with tempfile.TemporaryDirectory(prefix="casebook-fixtures-") as folder:
        for path in sorted((private / "tasks").glob("X-*.toml")):
            task = load_task(path)
            load_task_fixtures(builds[1], task.household_id, task.fixtures, task.cutoff, Path(folder) / task.task_id)
        try:
            prints = fingerprints(
                private,
                REPO,
                [*pair_files, *tree_files(Path(folder))],
                public_builds=public_files,
                approve_shared=args.approve_shared,
            )
        except SharedTextError as error:
            print(
                "fingerprints refused: the public repo also holds this private text, not yet approved as shared;",
                file=sys.stderr,
            )
            print(
                "if each is boilerplate the public files share (not a copy), rerun with --approve-shared:",
                file=sys.stderr,
            )
            print("  " + "\n  ".join(error.overlaps), file=sys.stderr)
            return 1
    FINGERPRINTS.write_text(json.dumps(prints, indent=2) + "\n", encoding="utf-8")
    print(f"{len(prints['files'])} private files and {len(prints['lines'])} lines fingerprinted into {FINGERPRINTS}")
    return 0


def _facts(args: argparse.Namespace) -> int:
    from casebook.generate.facts import write_fact_sheets

    written = write_fact_sheets(args.book, args.out)
    print(f"wrote {len(written)} fact sheets into {args.out}")
    return 0


def _tax(args: argparse.Namespace) -> int:
    from casebook.tax.summary import book_units, tax_report

    report = tax_report(book_units(args.book))
    print(report.render())
    return 0 if report.agrees else 1


def _freeze(args: argparse.Namespace) -> int:
    from casebook.runner.freeze import FreezeRefusedError, MoveInError, move_in, record_freeze

    if args.move_in:
        from casebook.runner.run import PrivateFolderError, private_root

        try:
            moved = move_in(private_root())
        except (MoveInError, PrivateFolderError) as error:
            print(f"move-in refused: {error}", file=sys.stderr)
            return 1
        print(f"moved the held-out pairs into {DEFAULT_SCRIPTS} and the ID ledger: {', '.join(moved)}")
        print("next: uv run casebook build --seed 2026, then casebook check and casebook site")
        return 0
    try:
        record = record_freeze()
    except FreezeRefusedError as error:
        print(f"freeze refused: {error}", file=sys.stderr)
        return 1
    hashes, tests = len(record["hashes"]), len(record["self_tests"])
    print(f"freeze recorded at {record['recorded_utc']}: {hashes} hashes; {tests} grader self-tests pass")
    return 0


def _audit_sheet(args: argparse.Namespace) -> int:
    from casebook.checks.audit_sheet import write_audit_sheet
    from casebook.seeding import derive_rng

    written = write_audit_sheet(args.book, args.out, derive_rng("audit", args.seed))
    print(f"wrote {len(written)} files into {args.out}")
    return 0


def _audit_log(args: argparse.Namespace) -> int:
    from casebook.checks.audit_log import audit_log_problems

    problems = audit_log_problems(args.log, args.worksheet)
    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"{args.log}: {len(problems)} problems")
    return 1 if problems else 0


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="casebook", description="The Indus Casebook")
    commands = top.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="build the book from a seed")
    build.add_argument("--seed", type=int, default=DEFAULT_SEED)
    build.add_argument("--out", type=Path, default=None, help=f"default {DEFAULT_BOOK}, or {REAL_BOOK}")
    build.add_argument("--real-tickers", action="store_true", help="real tickers with invented prices, for runs")
    build.add_argument("--scripts", type=Path, default=DEFAULT_SCRIPTS)
    build.add_argument(
        "--held-out",
        action="store_true",
        help="build the whole book, the held-out and private pairs too, into $CASEBOOK_PRIVATE",
    )
    build.set_defaults(run=_build)
    check = commands.add_parser("check", help="run every check on every household")
    check.add_argument("--book", type=Path, default=DEFAULT_BOOK)
    check.set_defaults(run=_check)
    site = commands.add_parser("site", help="build the public site from a checked book")
    site.add_argument("--book", type=Path, default=DEFAULT_BOOK)
    site.add_argument("--out", type=Path, default=DEFAULT_SITE)
    site.add_argument("--readme", type=Path, default=Path("README.md"))
    site.add_argument("--runs", type=Path, default=PUBLISHED_RUNS, help="mapped run records, for the task pages")
    site.add_argument("--tasks", type=Path, default=Path("tasks/public"))
    site.add_argument("--keys", type=Path, default=PUBLISHED_KEYS)
    site.add_argument("--errata", type=Path, default=Path("published/errata.json"), help="the errata log")
    site.set_defaults(run=_site)
    sample = commands.add_parser(
        "sample-book", help="write the sample book (the featured households, aliases only) into the plugin"
    )
    sample.add_argument("--book", type=Path, default=DEFAULT_BOOK)
    sample.add_argument("--out", type=Path, default=DEFAULT_SAMPLE_BOOK)
    sample.set_defaults(run=_sample_book)
    about = "write the preview release's bundle into out/release/<tag>/, gated whole (docs/PLAN.md, slice 16)"
    release = commands.add_parser("release", help=about, description=about)
    release.add_argument("--preview", action="store_true", required=True, help="the preview release, the only kind yet")
    release.add_argument("--book", type=Path, default=DEFAULT_BOOK)
    release.add_argument("--real-book", type=Path, default=REAL_BOOK, help="the real-ticker build the gate compares")
    release.add_argument("--out", type=Path, default=Path("out/release"))
    release.add_argument("--record", action="store_true", help="record this tag's IDs in published/releases.json")
    release.add_argument("--date", help="the release's date, with --record (YYYY-MM-DD)")
    release.set_defaults(run=_release)
    about = "write the tax reviewer's packet into out/review/<book version>/ and its zip (never published)"
    packet = commands.add_parser("review-packet", help=about, description=about)
    packet.add_argument("--book", type=Path, default=DEFAULT_BOOK)
    packet.add_argument("--out", type=Path, default=Path("out/review"))
    packet.set_defaults(run=_review_packet)
    run = commands.add_parser("run", help="run one task under one arm on the CLI under test")
    run.add_argument("--task", required=True)
    run.add_argument("--arm", required=True, choices=("basic", "checklist", "skill"))
    run.add_argument(
        "--book",
        type=Path,
        help="the real-ticker build a run reads: out/real/, or $CASEBOOK_PRIVATE/out/real/ for a private (X-) task",
    )
    run.add_argument(
        "--tasks", type=Path, help="the task files: tasks/public, or $CASEBOOK_PRIVATE/tasks for a private (X-) task"
    )
    run.add_argument("--keys", type=Path, default=PUBLISHED_KEYS)
    run.add_argument("--runs", type=Path, default=PUBLISHED_RUNS, help="where the mapped run records go")
    run.set_defaults(run=_run)
    about = (
        "run every task under every arm, three repeats each (a pass); a quota stop pauses it, and "
        "`casebook pass --resume <pass id>` starts what is left. Its state file is in $CASEBOOK_PRIVATE/passes/"
    )
    full = commands.add_parser("pass", help=about, description=about)
    which = full.add_mutually_exclusive_group()
    which.add_argument("--resume", metavar="PASS_ID", help="start the slots of a paused pass not yet completed")
    which.add_argument("--status", metavar="PASS_ID", help="show a pass's slots and every failed run with its reason")
    full.add_argument("--repeats", type=int, help="runs of each task under each arm (default: the spec's three)")
    full.add_argument(
        "--private",
        action="store_true",
        help="a new pass of the private set alone, under today's freeze (the owner's option 1a, 18 November 2026)",
    )
    full.add_argument("--tasks", type=Path, default=Path("tasks/public"), help="the public task files")
    full.add_argument("--private-tasks", type=Path, help="the private task files: default $CASEBOOK_PRIVATE/tasks")
    full.add_argument("--book", type=Path, default=REAL_BOOK, help="the real-ticker build the public tasks run on")
    full.add_argument(
        "--private-book", type=Path, help=f"the build the private tasks run on: default $CASEBOOK_PRIVATE/{REAL_BOOK}"
    )
    full.add_argument("--keys", type=Path, default=PUBLISHED_KEYS)
    full.add_argument("--runs", type=Path, default=PUBLISHED_RUNS, help="where the mapped run records go")
    full.set_defaults(run=_pass)
    about = (
        "grade a pass's public answers again under today's graders, with no new run and the jury's stored votes, "
        "keeping each run's earlier grade under `regraded`; refused unless the freeze matches today's hashes"
    )
    regrade = commands.add_parser("regrade", help=about, description=about)
    regrade.add_argument("pass_id", metavar="PASS_ID")
    regrade.set_defaults(run=_regrade)
    facts = commands.add_parser("facts", help="write each featured household's fact sheet, for its notes")
    facts.add_argument("--book", type=Path, default=DEFAULT_BOOK)
    facts.add_argument("--out", type=Path, default=Path("out/facts"))
    facts.set_defaults(run=_facts)
    tax = commands.add_parser("tax", help="compare the 2025 tax engine with Tax-Calculator and the keys, per household")
    tax.add_argument("--book", type=Path, default=DEFAULT_BOOK)
    tax.set_defaults(run=_tax)
    prints = commands.add_parser(
        "fingerprint-private",
        help="fingerprint the private set (book/private_fingerprints.json), so no public file can carry it",
    )
    prints.add_argument(
        "--approve-shared",
        action="store_true",
        help="approve, as boilerplate the public files share, private text the public repo also holds",
    )
    prints.set_defaults(run=_fingerprint_private)
    about = (
        "record the freeze: the hashes of every skill, the checklist and every grader, refused while a grader's "
        "self-test (the tests of its key and grade modules) fails. Held-out runs are refused unless it matches. Then "
        "`casebook freeze --move-in` moves the held-out pairs into the repo"
    )
    freeze = commands.add_parser("freeze", help=about, description=about)
    freeze.add_argument(
        "--move-in",
        action="store_true",
        help="once the freeze is recorded, move the held-out pairs from $CASEBOOK_PRIVATE into book/scripted/ "
        "and the ID ledger",
    )
    freeze.set_defaults(run=_freeze)
    sheet = commands.add_parser("audit-sheet", help="write the hand audit's line-by-line worksheet")
    sheet.add_argument("--book", type=Path, default=DEFAULT_BOOK)
    sheet.add_argument("--out", type=Path, default=DEFAULT_AUDIT)
    sheet.add_argument("--seed", type=int, default=DEFAULT_SEED, help="the seed of the draw of households")
    sheet.set_defaults(run=_audit_sheet)
    log = commands.add_parser("audit-log", help="check the hand audit's log against its worksheet")
    log.add_argument("--check", action="store_true", required=True, help="exit 1 naming each problem")
    log.add_argument("--log", type=Path, default=AUDIT_LOG)
    log.add_argument("--worksheet", type=Path, default=DEFAULT_AUDIT / BOOK_VERSION / "worksheet.csv")
    log.set_defaults(run=_audit_log)
    canary = commands.add_parser("canary", help="check a run cannot read a sealed file outside its workspace")
    canary.set_defaults(run=_canary)
    return top


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return int(args.run(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
