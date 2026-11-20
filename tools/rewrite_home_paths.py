"""Rewrite the home-folder paths in the committed published files, once, before the preview release.

The owner's choice 5(a) of 19 November 2026 (docs/decisions/2026-11-19-slice16-release-choices.md): a path inside
the repo becomes relative to it, one outside it a placeholder naming its role (`casebook.publish.mapper`, as the
runner now publishes). Each JSON file is read and written back as it was written (records sorted with an indent of
two, transcript lines as `json.dumps` writes them), so only the rewritten strings change; a file that does not
read back byte for byte is refused, not rewritten. A record whose hashes, grade, regrade or freeze the rewrite would
touch is refused too: no grade and no hash changes.

    uv run python tools/rewrite_home_paths.py --private ../indus-casebook-private [--dry-run]
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from casebook.publish.mapper import path_rewriter, without_home_paths
from casebook.runner.config import REPO

PUBLISHED = Path("published")
# A record's fields that the rewrite must leave as they are, or the file is refused.
KEPT = ("hashes", "grade", "regraded", "freeze", "output", "crm_sandbox_diff")
# What still counts as a home-folder path once the rewrite is done: the folders the decision names.
LEFTOVER = re.compile(r"/Users/|/home/|/private/var/folders|/var/folders/|/private/tmp|(?<![A-Za-z0-9._-])/tmp/")


class RewriteRefusedError(RuntimeError):
    pass


def kind(relative: Path) -> str:
    """records, transcripts, keys, results, audit, or the published file's own name."""
    if relative.parts[0] == "runs":
        return "transcripts" if relative.name.endswith(".jsonl") else "records"
    return relative.parts[0] if len(relative.parts) > 1 else relative.name


def changed_fields(before: Any, after: Any, where: str = "") -> Iterator[str]:
    """Where two JSON values differ, as `.field[].field`; a tool call's own ID as `<id>`."""
    if isinstance(before, dict) and isinstance(after, dict):
        for (key, old), new in zip(before.items(), after.values(), strict=True):  # pyright: ignore[reportUnknownVariableType]
            name = "<id>" if str(key).startswith("toolu_") else str(key)  # pyright: ignore[reportUnknownArgumentType]
            yield from changed_fields(old, new, f"{where}.{name}")
    elif isinstance(before, list) and isinstance(after, list):
        for old, new in zip(before, after, strict=True):  # pyright: ignore[reportUnknownVariableType]
            yield from changed_fields(old, new, f"{where}[]")
    elif before != after:
        yield where or "."


@dataclass
class Report:
    files: Counter[str] = field(default_factory=Counter[str])
    fields: Counter[tuple[str, str]] = field(default_factory=Counter[tuple[str, str]])

    def lines(self) -> list[str]:
        shown = [f"{n} {k} files rewritten" for k, n in sorted(self.files.items())]
        return shown + [f"{n} {k} {f}" for (k, f), n in sorted(self.fields.items())]


def _record_text(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def rewrite_json(text: str, rewrite: Callable[[str], str], where: str) -> tuple[str, list[str]]:
    before = json.loads(text)
    after = without_home_paths(before, rewrite)
    if after == before:
        return text, []
    if _record_text(before) != text:
        raise RewriteRefusedError(f"{where} does not read back as written; rewrite it by hand")
    if isinstance(before, dict):
        touched = [name for name in KEPT if before.get(name) != after.get(name)]  # pyright: ignore[reportUnknownMemberType]
        if touched:
            raise RewriteRefusedError(f"{where}: the rewrite would change {', '.join(touched)}")
    return _record_text(after), list(changed_fields(before, after))


def rewrite_jsonl(text: str, rewrite: Callable[[str], str], where: str) -> tuple[str, list[str]]:
    lines = text.split("\n")
    if lines[-1] != "":
        raise RewriteRefusedError(f"{where} does not end in a newline")
    out: list[str] = []
    fields: list[str] = []
    for line in lines[:-1]:
        before = json.loads(line)
        after = without_home_paths(before, rewrite)
        if after == before:
            out.append(line)
            continue
        if json.dumps(before) != line:
            raise RewriteRefusedError(f"{where}: a line does not read back as written; rewrite it by hand")
        out.append(json.dumps(after))
        fields += changed_fields(before, after)
    return "\n".join(out) + "\n", fields


def rewrite_file(path: Path, rewrite: Callable[[str], str], where: str) -> tuple[str, list[str]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return rewrite_json(text, rewrite, where)
    if path.suffix == ".jsonl":
        return rewrite_jsonl(text, rewrite, where)
    after = rewrite(text)
    return after, ["(text)"] if after != text else []


def rewrite_published(published: Path, private: Path, write: bool = True) -> Report:
    """Every published file holding a home-folder path, rewritten (or, unless `write`, only counted); refused
    before any is written if one cannot be, or if one would still hold such a path."""
    rewrite = path_rewriter(REPO, private)
    report = Report()
    pending: dict[Path, str] = {}
    for path in sorted(p for p in published.rglob("*") if p.is_file()):
        relative = path.relative_to(published)
        text, fields = rewrite_file(path, rewrite, relative.as_posix())
        if LEFTOVER.search(text) or private.as_posix() in text:
            raise RewriteRefusedError(f"{relative.as_posix()} would still hold a home-folder path")
        if fields:
            pending[path] = text
            report.files[kind(relative)] += 1
            report.fields.update((kind(relative), f) for f in fields)
    if write:
        for path, text in pending.items():
            path.write_text(text, encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--published", type=Path, default=PUBLISHED)
    parser.add_argument("--private", type=Path, default=os.environ.get("CASEBOOK_PRIVATE"))
    parser.add_argument("--dry-run", action="store_true", help="count what would change; write nothing")
    args = parser.parse_args(argv)
    if args.private is None:
        print("name the private folder: --private, or $CASEBOOK_PRIVATE", file=sys.stderr)
        return 2
    try:
        report = rewrite_published(args.published, args.private.resolve(), write=not args.dry_run)
    except RewriteRefusedError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    print("\n".join(report.lines()) or "no home-folder path found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
