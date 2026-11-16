"""`casebook site`: render the site from a checked book, copy the published files, then gate it."""

import shutil
from pathlib import Path

from casebook.checks import check_book
from casebook.model.files import MANIFEST, METADATA, read_manifest
from casebook.publish.gates import run_gates
from casebook.site import STATIC_DIR, data_root, render_site


class SiteBuildError(RuntimeError):
    pass


def build_site(book: Path, out: Path, readme: Path) -> int:
    report = check_book(book)
    if not report.passed:
        failed = ", ".join(sorted(report.failed_households()))
        raise SiteBuildError(f"households failed their checks and cannot be published: {failed}")
    manifest = read_manifest(book)
    staging = out.with_name(out.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    pages = render_site(book)
    for name, html in pages.items():
        path = staging / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
    shutil.copytree(STATIC_DIR, staging / "static")
    data = staging / data_root(manifest.version)
    for name in [*manifest.files, MANIFEST]:
        target = data / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(book / name, target)
    problems = run_gates(staging, readme, data / METADATA)
    if problems:
        raise SiteBuildError("the site fails its gates:\n  " + "\n  ".join(problems))
    if out.exists():
        shutil.rmtree(out)
    staging.rename(out)
    return len(pages)
