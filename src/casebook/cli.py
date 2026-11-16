"""The one `casebook` command."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from casebook import BOOK_VERSION

DEFAULT_SEED = 2026
DEFAULT_BOOK = Path("out/book") / BOOK_VERSION
DEFAULT_SITE = Path("out/site")
DEFAULT_SCRIPTS = Path("book/scripted")


def _build(args: argparse.Namespace) -> int:
    from casebook.build import build_book

    result = build_book(args.seed, args.out, args.scripts)
    print(f"built {len(result.households)} households, {result.files} files, into {result.root}")
    return 0


def _check(args: argparse.Namespace) -> int:
    from casebook.checks import check_book

    report = check_book(args.book)
    sys.stdout.write(report.render())
    return 0 if report.passed else 1


def _site(args: argparse.Namespace) -> int:
    from casebook.publish.site_build import SiteBuildError, build_site

    try:
        pages = build_site(args.book, args.out, args.readme)
    except SiteBuildError as error:
        print(f"site build failed: {error}", file=sys.stderr)
        return 1
    print(f"built {pages} pages into {args.out}")
    return 0


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="casebook", description="The Indus Casebook")
    commands = top.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="build the book from a seed")
    build.add_argument("--seed", type=int, default=DEFAULT_SEED)
    build.add_argument("--out", type=Path, default=DEFAULT_BOOK)
    build.add_argument("--scripts", type=Path, default=DEFAULT_SCRIPTS)
    build.set_defaults(run=_build)
    check = commands.add_parser("check", help="run every check on every household")
    check.add_argument("--book", type=Path, default=DEFAULT_BOOK)
    check.set_defaults(run=_check)
    site = commands.add_parser("site", help="build the public site from a checked book")
    site.add_argument("--book", type=Path, default=DEFAULT_BOOK)
    site.add_argument("--out", type=Path, default=DEFAULT_SITE)
    site.add_argument("--readme", type=Path, default=Path("README.md"))
    site.set_defaults(run=_site)
    return top


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return int(args.run(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
