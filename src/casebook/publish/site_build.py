"""`casebook site`: render the site from a checked book, copy the published files, then gate it."""

import shutil
from pathlib import Path

from casebook.checks import check_book
from casebook.model.archetypes import HELD_OUT_ARCHETYPES, frozen
from casebook.model.files import (
    ALIASES,
    MANIFEST,
    METADATA,
    SEALED_HOUSEHOLDS,
    is_tax_summary,
    read_json,
    read_manifest,
)
from casebook.publish.gates import run_gates
from casebook.site import STATIC_DIR, data_root, render_site


class SiteBuildError(RuntimeError):
    pass


RUNS_DATA = "data/runs"


def build_site(
    book: Path, out: Path, readme: Path, runs: Path | None = None, tasks: Path | None = None, keys: Path | None = None
) -> int:
    if read_json(book, METADATA).get("securities") != ALIASES:
        raise SiteBuildError(f"{book} is not a default build; a real-ticker build is never published")
    held = sorted(
        h["household_id"]
        for h in read_json(book, SEALED_HOUSEHOLDS)["households"]
        if h["set"] == "featured" and h["archetype"] in HELD_OUT_ARCHETYPES
    )
    if held and not frozen():
        raise SiteBuildError(f"{', '.join(held)}: held out until the freeze, so not on the site")
    report = check_book(book)
    if not report.passed:
        failed = ", ".join(sorted(report.failed_households()))
        raise SiteBuildError(f"households failed their checks and cannot be published: {failed}")
    manifest = read_manifest(book)
    staging = out.with_name(out.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    keys_dir = keys / manifest.version if keys else None
    pages = render_site(book, runs, tasks, keys_dir)
    for name, html in pages.items():
        path = staging / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
    shutil.copytree(STATIC_DIR, staging / "static")
    data = staging / data_root(manifest.version)
    # Every book file but the tax summaries, which stay off the site until the tax review.
    for name in [*(n for n in manifest.files if not is_tax_summary(n)), MANIFEST]:
        target = data / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(book / name, target)
    if runs and runs.is_dir():
        for path in sorted(p for p in runs.rglob("*") if p.is_file()):
            target = staging / RUNS_DATA / path.relative_to(runs)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    problems = run_gates(staging, readme, data / METADATA)
    if problems:
        raise SiteBuildError("the site fails its gates:\n  " + "\n  ".join(problems))
    if out.exists():
        shutil.rmtree(out)
    staging.rename(out)
    return len(pages)
