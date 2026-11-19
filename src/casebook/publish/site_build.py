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
from casebook.publish.gates import run_gates, run_layout_problems, unmapped_record_problems
from casebook.publish.private_set import private_set_problems
from casebook.site import STATIC_DIR, data_root, render_site
from casebook.site.errata import ErrataError
from casebook.site.results import ResultsError, private_outcomes_path
from casebook.site.tasks import is_held
from casebook.tasks.task import load_task


class SiteBuildError(RuntimeError):
    pass


RUNS_DATA = "data/runs"


def build_site(
    book: Path,
    out: Path,
    readme: Path,
    runs: Path | None = None,
    tasks: Path | None = None,
    keys: Path | None = None,
    private_outcomes: Path | None = None,
    errata: Path | None = None,
) -> int:
    """`private_outcomes`: the private set's published counts, by default beside the runs in `published/results/`.
    `errata`: the errata log, `published/errata.json`; with none, the log's page says there is no correction yet."""
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
    # The private set is refused at the door as well as in the finished site: a private run or key among the
    # inputs would otherwise stop the build at its task page, with no word of why.
    if private_outcomes is None and runs is not None:
        private_outcomes = private_outcomes_path(runs)
    summary = private_outcomes.parent if private_outcomes is not None else None
    private = [
        p
        for folder in (runs, tasks, keys, summary)
        if folder is not None and folder.is_dir()
        for p in private_set_problems(folder)
    ]
    if private:
        raise SiteBuildError("the site's inputs hold the private set:\n  " + "\n  ".join(private))
    misplaced = run_layout_problems(runs) if runs is not None and runs.is_dir() else []
    if misplaced:
        raise SiteBuildError("the site's inputs hold files outside the runs' layout:\n  " + "\n  ".join(misplaced))
    unmapped = unmapped_record_problems(runs) if runs is not None and runs.is_dir() else []
    if unmapped:
        raise SiteBuildError("the site's inputs hold unmapped run records:\n  " + "\n  ".join(unmapped))
    manifest = read_manifest(book)
    staging = out.with_name(out.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    keys_dir = keys / manifest.version if keys else None
    try:
        pages = render_site(book, runs, tasks, keys_dir, private_outcomes, errata)
    except ResultsError as error:
        raise SiteBuildError(f"the results page cannot be built: {error}") from error
    except ErrataError as error:
        raise SiteBuildError(f"the errata log cannot be built: {error}") from error
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
    shown = [load_task(tasks / f"{Path(n).stem}.toml") for n in pages if n.startswith("tasks/")] if tasks else []
    held = {t.task_id: t.justified_conclusion for t in shown if is_held(t)}
    problems = run_gates(staging, readme, data / METADATA, held)
    if problems:
        raise SiteBuildError("the site fails its gates:\n  " + "\n  ".join(problems))
    if out.exists():
        shutil.rmtree(out)
    staging.rename(out)
    return len(pages)
