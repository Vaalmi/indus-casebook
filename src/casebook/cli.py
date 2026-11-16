"""The one `casebook` command."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from casebook import BOOK_VERSION

DEFAULT_SEED = 2026
DEFAULT_BOOK = Path("out/book") / BOOK_VERSION
REAL_BOOK = Path("out/real") / BOOK_VERSION
DEFAULT_SITE = Path("out/site")
DEFAULT_SCRIPTS = Path("book/scripted")
# Release files kept in the repo, so a tag builds the same site: mapped run records and the
# keys that may be published (docs/SPEC.md, Running it: "Run records and transcripts are kept
# as release files").
PUBLISHED_RUNS = Path("published/runs")
PUBLISHED_KEYS = Path("published/keys")


def _build(args: argparse.Namespace) -> int:
    from casebook.build import BuildError, build_book
    from casebook.generate.script import ScriptError

    out = args.out or (REAL_BOOK if args.real_tickers else DEFAULT_BOOK)
    scripts = args.scripts
    if args.held_out:
        from casebook.runner.run import PrivateFolderError, private_root

        try:
            private = private_root()
        except PrivateFolderError as error:
            print(f"build failed: {error}", file=sys.stderr)
            return 1
        scripts = args.scripts if args.scripts != DEFAULT_SCRIPTS else private / DEFAULT_SCRIPTS
        out = args.out or private / out
    try:
        result = build_book(args.seed, out, scripts, args.real_tickers, held_out=args.held_out)
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
        pages = build_site(args.book, args.out, args.readme, args.runs, args.tasks, args.keys)
    except (SiteBuildError, UnnamedResultError) as error:
        print(f"site build failed: {error}", file=sys.stderr)
        return 1
    print(f"built {pages} pages into {args.out}")
    return 0


def _run(args: argparse.Namespace) -> int:
    from casebook.runner.config import SharedConfig
    from casebook.runner.preflight import RunRefusedError
    from casebook.runner.session import run_and_grade

    try:
        record = run_and_grade(args.task, args.arm, args.tasks, args.book, args.keys, args.runs, SharedConfig())
    except RunRefusedError as error:
        print(f"run refused: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    grade = record["grade"] or {}
    print(f"{record['run_id']}: {record['state']}", end="")
    print(f", {record['failure_reason']}" if record["failure_reason"] else f", score {grade.get('score')}")
    return 0 if record["state"] != "failed" else 1


def _canary(args: argparse.Namespace) -> int:
    from casebook.runner.canary import run_canary
    from casebook.runner.config import SharedConfig
    from casebook.runner.run import private_root

    result = run_canary(SharedConfig(), keep=private_root() / "canary")
    print(f"canary: {'LEAKED' if result.leaked else 'no leak'}; the CLI {result.failure or 'finished cleanly'}")
    print(result.final_text)
    return 1 if result.leaked or result.failure else 0


def _facts(args: argparse.Namespace) -> int:
    from casebook.generate.facts import write_fact_sheets

    written = write_fact_sheets(args.book, args.out)
    print(f"wrote {len(written)} fact sheets into {args.out}")
    return 0


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="casebook", description="The Indus Casebook")
    commands = top.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="build the book from a seed")
    build.add_argument("--seed", type=int, default=DEFAULT_SEED)
    build.add_argument("--out", type=Path, default=None, help=f"default {DEFAULT_BOOK}, or {REAL_BOOK}")
    build.add_argument("--real-tickers", action="store_true", help="real tickers with invented prices, for runs")
    build.add_argument("--scripts", type=Path, default=DEFAULT_SCRIPTS)
    build.add_argument(
        "--held-out", action="store_true", help="build the held-out pairs from $CASEBOOK_PRIVATE, into it"
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
    site.set_defaults(run=_site)
    run = commands.add_parser("run", help="run one task under one arm on the CLI under test")
    run.add_argument("--task", required=True)
    run.add_argument("--arm", required=True, choices=("basic", "checklist", "skill"))
    run.add_argument("--book", type=Path, default=REAL_BOOK, help="runs read the real-ticker build")
    run.add_argument("--tasks", type=Path, default=Path("tasks/public"))
    run.add_argument("--keys", type=Path, default=PUBLISHED_KEYS)
    run.add_argument("--runs", type=Path, default=PUBLISHED_RUNS, help="where the mapped run records go")
    run.set_defaults(run=_run)
    facts = commands.add_parser("facts", help="write each featured household's fact sheet, for its notes")
    facts.add_argument("--book", type=Path, default=DEFAULT_BOOK)
    facts.add_argument("--out", type=Path, default=Path("out/facts"))
    facts.set_defaults(run=_facts)
    canary = commands.add_parser("canary", help="check a run cannot read a sealed file outside its workspace")
    canary.set_defaults(run=_canary)
    return top


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return int(args.run(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
