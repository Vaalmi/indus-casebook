"""The preview release's gates (docs/PLAN.md, slice 16, criterion 1): each refusal planted into a small real bundle
built from the book fixture and the committed published files, and the clean bundle passing."""

import hashlib
import io
import json
import os
import shutil
from html import escape
from pathlib import Path

import pytest
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate

import casebook.tax.forms
from casebook.graders.registry import grader
from casebook.model.files import json_text, read_manifest
from casebook.notice import NOTICE, contains_notice
from casebook.publish.release_gates import HeldMaterial, held_material, release_problems
from casebook.publish.site_build import build_site
from casebook.publish.zips import read_zip, write_zip
from casebook.published_text import pdf_pages_text
from casebook.runner.session import write_key
from casebook.tasks.task import load_task

from .conftest import README, ROOT

PUBLISHED = ROOT / "published"
TASKS = ROOT / "tasks" / "public"
VERSION = "0.0.1"
# A task whose verdict may be published (reconciliation) and a held one (tax-lot and RMD), with their runs.
OPEN_TASK, HELD_TASK = "T-REC-01", "T-TAX-01"
PACKET = "HH-4821"
NOTICE_TEXT = NOTICE + "\n"
# A blank official form: a fillable PDF with no watermark and no notice.
BLANK_FORM = Path(casebook.tax.forms.__file__).parent / "pdfs" / "f1040--2025.pdf"
# The README's committed images (A-D2: the release ships them beside the README).
IMAGES = ROOT / "docs" / "images"


def _plain(text: str) -> str:
    """A committed run's text with this checkout's folder taken out, as choice 5a rewrites it before a release."""
    return text.replace(f"{ROOT}/", "")


def _noticed(path: Path) -> str:
    """Published JSON as the release ships it: with a top-level notice (choice 2)."""
    return json_text({**json.loads(path.read_text()), "notice": NOTICE})


def _write(path: Path, data: str | bytes) -> None:
    """Write a file of a bundle whose files may be links to another's: unlinked first, so the other keeps its own."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)


def _pdf(text: str) -> bytes:
    """A PDF with no form whose one page says `text`: what a filled return is once flattened."""
    out = io.BytesIO()
    SimpleDocTemplate(out).build([Paragraph(text, getSampleStyleSheet()["Normal"])])
    return out.getvalue()


def _key(task_id: str, book: Path) -> str:
    """A task's key as `casebook run` writes it, computed on `book`."""
    task = load_task(TASKS / f"{task_id}.toml")
    return json_text(grader(task.grader).key(book, task.household_id, task.grader_params).to_dict())


def _packet(book: Path, household: str, extra: dict[str, bytes] | None = None) -> bytes:
    manifest = read_manifest(book)
    files = {n: (book / n).read_bytes() for n in manifest.files if n.startswith(f"households/{household}/")}
    files |= {n: (book / n).read_bytes() for n in ("metadata.json", "securities/securities.csv")}
    files["NOTICE.txt"] = NOTICE_TEXT.encode()
    files["answer-sheet.json"] = json_text({"notice": NOTICE, "household_id": household, "keys": []}).encode()
    return write_zip(files | (extra or {}))


@pytest.fixture(scope="module")
def held_keys(book: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The held task's key as `casebook run` writes it, into a folder standing for out/keys/."""
    root = tmp_path_factory.mktemp("held-keys")
    task = load_task(TASKS / f"{HELD_TASK}.toml")
    write_key(task.task_id, grader(task.grader).key(book, task.household_id, task.grader_params), root, VERSION)
    return root


@pytest.fixture(scope="module")
def held(book: Path, real_book: Path, tmp_path_factory: pytest.TempPathFactory) -> HeldMaterial:
    """As a fresh clone has it: no out/keys/ (reviewers A and B, slice 16 round 1)."""
    return held_material(book, real_book, TASKS, tmp_path_factory.mktemp("no-held-keys"), IMAGES)


@pytest.fixture(scope="module")
def clean(book: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A release bundle laid out as the contract gives it (review/slice16-contract.md), small: the book fixture's
    households, and the runs of one open and one held task."""
    bundle = tmp_path_factory.mktemp("release") / "v0.1.0"
    bundle.mkdir()
    for name in ("LICENSE", "LICENSE-DATA", "README.md"):
        shutil.copyfile(ROOT / name, bundle / name)
    _write(bundle / "NOTICE.txt", NOTICE_TEXT)
    release = {"notice": NOTICE, "tag": "v0.1.0", "package_version": "0.1.0", "book_version": VERSION, "seed": 2026}
    _write(bundle / "release.json", json_text(release))
    manifest = read_manifest(book)
    for name in [*(n for n in manifest.files if not n.endswith("/tax_summary.json")), "manifest.json"]:
        _write(bundle / "book" / name, (book / name).read_bytes())
    for task in (OPEN_TASK, HELD_TASK):
        for path in sorted((PUBLISHED / "runs" / task).iterdir()):
            _write(bundle / "runs" / task / path.name, _plain(path.read_text()))
    for path in sorted((PUBLISHED / "keys" / VERSION).glob("*.json")):
        _write(bundle / "keys" / path.name, _noticed(path))
    _write(bundle / "results" / "private-outcomes.json", (PUBLISHED / "results" / "private-outcomes.json").read_text())
    _write(bundle / "audit" / "audit-log.csv", (PUBLISHED / "audit" / "audit-log.csv").read_text())
    _write(bundle / "audit" / "AUDIT.md", "> " + NOTICE + "\n\n" + (PUBLISHED / "audit" / "AUDIT.md").read_text())
    _write(bundle / "audit" / "NOTICE.txt", NOTICE_TEXT)
    for name in ("errata.json", "freeze.json"):
        _write(bundle / name, _noticed(PUBLISHED / name))
    build_site(
        book,
        bundle / "site",
        README,
        runs=bundle / "runs",
        tasks=TASKS,
        keys=PUBLISHED / "keys",
        private_outcomes=PUBLISHED / "results" / "private-outcomes.json",
        errata=PUBLISHED / "errata.json",
    )
    _write(bundle / "site" / "NOTICE.txt", NOTICE_TEXT)  # the stylesheet carries no notice of its own
    for path in sorted(IMAGES.iterdir()):
        _write(bundle / "docs" / "images" / path.name, path.read_bytes())
    _write(bundle / "docs" / "images" / "NOTICE.txt", NOTICE_TEXT)
    packet = _packet(book, PACKET)
    _write(bundle / "packets" / f"{PACKET}.zip", packet)
    _write(bundle / "site" / "packets" / f"{PACKET}.zip", packet)
    return bundle


@pytest.fixture
def bundle(clean: Path, tmp_path: Path) -> Path:
    """A copy of the clean bundle to plant a failure into: its files are links to the clean one's, so it costs
    almost nothing; `_write` replaces a file without touching the clean bundle's."""
    copy = tmp_path / "v0.1.0"
    shutil.copytree(clean, copy, copy_function=os.link)
    return copy


def only(problems: list[str], *wanted: str) -> list[str]:
    return [p for p in problems if any(w in p for w in wanted)]


def test_the_clean_bundle_passes(clean: Path, held: HeldMaterial) -> None:
    assert release_problems(clean, held) == []


def test_the_held_material_is_the_held_tasks_keys_and_tax_summaries(
    held: HeldMaterial, book: Path, real_book: Path, tmp_path: Path
) -> None:
    # 17 of the 24 public tasks are held (review/slice16-contract.md; docs/STATUS.md, slice 14).
    assert len(held.tasks) == 17
    assert {"T-TAX-01", "T-TAX-06", "T-REC-03", "T-MTG-01", "T-CMP-01"} <= held.tasks.keys()
    assert {"T-REC-01", "T-REC-02", "T-CMP-05"}.isdisjoint(held.tasks)
    assert len(held.open_tasks) == 7 and {"T-REC-01", "T-REC-02", "T-CMP-05"} <= held.open_tasks
    assert held.real_only
    assert sorted(held.images) == [
        "household-planted-item.png",
        "household-source-sets.png",
        "results-page.png",
        "site-home.png",
        "task-arms.png",
    ]
    # A held key in out/keys/ still counts, though the gate computes every held key itself.
    stale = tmp_path / VERSION / f"{HELD_TASK}.json"
    stale.parent.mkdir()
    stale.write_text(json_text({"stale": "a held key from an older book"}), encoding="utf-8")
    assert hashlib.sha256(stale.read_bytes()).hexdigest() not in held.answers
    with_stale = held_material(book, real_book, TASKS, tmp_path, IMAGES)
    assert hashlib.sha256(stale.read_bytes()).hexdigest() in with_stale.answers


# 1. A tax or RMD answer key, a tax answer sheet, or a verdict on a tax-lot or RMD task.


def test_a_held_key_fails_by_its_bytes_its_content_or_its_place(
    bundle: Path, held: HeldMaterial, held_keys: Path, book: Path, real_book: Path
) -> None:
    # The gate's held material comes from no out/keys/, as in a fresh clone (A-S1, B-S1): each key is known from
    # either build, and inside a list (B-S2).
    key_file = held_keys / VERSION / f"{HELD_TASK}.json"
    _write(bundle / "site" / "data" / "extra.json", key_file.read_bytes())
    _write(bundle / "keys" / f"{HELD_TASK}.json", _noticed(key_file))
    _write(bundle / "audit" / "T-TAX-06.json", json_text({**json.loads(_key("T-TAX-06", book)), "notice": NOTICE}))
    _write(bundle / "keys" / "old-tax-key.json", _key("T-REC-03", real_book))
    export = {"notice": NOTICE, "answers": [json.loads(_key("T-MTG-01", book))]}
    _write(bundle / "results" / "export.json", json_text(export))
    sheet = {
        "notice": NOTICE,
        "household_id": PACKET,
        "keys": [{"task_id": HELD_TASK, "key": json.loads(key_file.read_text())}],
    }
    _write(
        bundle / "packets" / f"{PACKET}.zip", _packet(book, PACKET, {"answer-sheet.json": json_text(sheet).encode()})
    )
    assert only(release_problems(bundle, held), "held task's answer key", "key of held task") == [
        "audit/T-TAX-06.json: holds a held task's answer key or a tax answer sheet",
        f"keys/{HELD_TASK}.json: holds a held task's answer key or a tax answer sheet",
        "keys/old-tax-key.json: a held task's answer key or a tax answer sheet",
        "keys/old-tax-key.json: holds a held task's answer key or a tax answer sheet",
        f"packets/{PACKET}.zip!answer-sheet.json: holds a held task's answer key or a tax answer sheet",
        "results/export.json: holds a held task's answer key or a tax answer sheet",
        "site/data/extra.json: a held task's answer key or a tax answer sheet",
        "site/data/extra.json: holds a held task's answer key or a tax answer sheet",
        f"keys/{HELD_TASK}.json: the key of held task {HELD_TASK}",
    ]


def test_a_held_key_written_into_a_text_file_fails(bundle: Path, held: HeldMaterial, held_keys: Path) -> None:
    """Whole-branch review, reviewer B: a held key fenced inside the README shipped."""
    key = (held_keys / VERSION / f"{HELD_TASK}.json").read_text()
    readme = bundle / "README.md"
    _write(readme, readme.read_text() + f"\n```json\n{key}\n```\n")
    page = bundle / "site" / "tasks" / f"{HELD_TASK}.html"
    shown = escape(json.dumps(json.loads(key), indent=1))
    _write(page, page.read_text().replace("</main>", f"<pre>{shown}</pre></main>"))
    # Round 2: in a comment, which no reader sees but the page's source carries.
    results = bundle / "site" / "results.html"
    _write(results, results.read_text().replace("</main>", f"<!-- debug {key} --></main>"))
    assert only(release_problems(bundle, held), "in its text") == [
        "README.md: holds a held task's answer key or a tax answer sheet in its text",
        "site/results.html: holds a held task's answer key or a tax answer sheet in its text",
        f"site/tasks/{HELD_TASK}.html: holds a held task's answer key or a tax answer sheet in its text",
    ]


def test_a_tax_summary_fails(bundle: Path, held: HeldMaterial, book: Path) -> None:
    summary = "sealed/HH-5271/tax_summary.json"
    _write(bundle / "book" / summary, (book / summary).read_bytes())
    assert only(release_problems(bundle, held), "tax_summary") == [
        f"book/{summary}: a held task's answer key or a tax answer sheet",
        f"book/{summary}: a tax summary, a tax answer sheet held until the tax review",
        f"book/{summary}: holds a held task's answer key or a tax answer sheet",
        f"book/{summary}: not a file the release's book ships (its manifest's, less the tax summaries)",
    ]


def test_a_verdict_on_a_held_task_fails(bundle: Path, held: HeldMaterial) -> None:
    record = sorted((bundle / "runs" / HELD_TASK).glob("*.json"))[0]
    data = json.loads(record.read_text())
    _write(record, json_text({**data, "grade": {"score": 100}}))
    site_record = bundle / "site" / "data" / "runs" / HELD_TASK / record.name
    _write(site_record, json_text({**data, "regraded": {**data["regraded"], "grade_before": {"score": 0}}}))
    page = bundle / "site" / "tasks" / f"{HELD_TASK}.html"
    _write(page, page.read_text().replace("</main>", "<p>Skill: 100 of 100</p></main>"))
    assert only(release_problems(bundle, held), "carries its grade", "verdict") == [
        f"site/tasks/{HELD_TASK}.html: a held task's page shows a verdict",
        f"site/data/runs/{HELD_TASK}/{record.name}: a held task's run record carries its grade",
        f"runs/{HELD_TASK}/{record.name}: a held task's run record carries its grade",
    ]


# 2. A combined score: a field, or a number shown as one; the results page's "there is no combined score" passes.


def test_a_combined_score_fails(bundle: Path, held: HeldMaterial) -> None:
    keys = ["combined_score", "Overall-Score", "aggregatescore", "totalScore", "mean_score"]
    workflows = [{"workflow": "reconciliation", key: 87} for key in keys]
    _write(bundle / "results" / "scores.json", json_text({"notice": NOTICE, "workflows": workflows}))
    _write(bundle / "audit" / "summary.csv", "workflow,Overall Score\nreconciliation,87\n")  # B-S4
    shown = {
        "results.html": "<p>Combined score: 87</p>",
        "index.html": "<table><tr><td>Overall score</td><td>92.5</td></tr></table>",
        "errata.html": "<p>71% overall score</p>",
    }
    for name, html in shown.items():
        page = bundle / "site" / name
        _write(page, page.read_text().replace("</main>", html + "</main>"))
    assert only(release_problems(bundle, held), "combined score") == [
        "audit/summary.csv: a combined score (Overall Score)",
        "results/scores.json: a combined score (Overall-Score, aggregatescore, combined_score, mean_score, totalScore)",
        "site/errata.html: shows a combined score",
        "site/index.html: shows a combined score",
        "site/results.html: shows a combined score",
    ]


# 3. A household with a failed check, or one the checked book does not hold.


def test_a_household_that_fails_a_check_fails(bundle: Path, held: HeldMaterial) -> None:
    _write(
        bundle / "book" / "households" / "HH-7350" / "custodian" / "positions.csv",
        "account_id,security_id,security,units,price,price_label,market_value,valuation_date,known_as_of\n",
    )
    positions = "households/HH-7350/custodian/positions.csv"
    assert only(release_problems(bundle, held), "HH-7350") == [
        f"book/{positions}: not the bytes the book's manifest lists for {positions}",
        f"site/data/{VERSION}/{positions}: not the release's book/{positions}",
        "book/households/HH-7350: fails its checks",
    ]


def test_a_household_the_checked_book_does_not_hold_fails(bundle: Path, held: HeldMaterial, book: Path) -> None:
    accounts = f"households/{PACKET}/custodian/accounts.csv"
    _write(bundle / "book" / "households" / "HH-0001" / "custodian" / "accounts.csv", (book / accounts).read_bytes())
    changed = (book / accounts).read_text().replace("joint_taxable", "individual_taxable", 1).encode()
    _write(bundle / "packets" / f"{PACKET}.zip", _packet(book, PACKET, {accounts: changed}))
    assert only(release_problems(bundle, held), "HH-0001", "accounts.csv") == [
        "book/households/HH-0001/custodian/accounts.csv: not a file the release's book ships (its manifest's, "
        "less the tax summaries)",
        f"packets/{PACKET}.zip!{accounts}: not the release's book/{accounts}",
        "book/households/HH-0001: a household the book's manifest does not list",
    ]


# 4. A real ticker or security name, a price without the synthetic label, anything of the private set.


def test_a_real_ticker_or_name_fails_in_a_file_or_a_zip_member(bundle: Path, held: HeldMaterial, book: Path) -> None:
    sheet = {"notice": NOTICE, "household_id": PACKET, "note": "holds JNJ"}
    _write(
        bundle / "packets" / f"{PACKET}.zip", _packet(book, PACKET, {"answer-sheet.json": json_text(sheet).encode()})
    )
    page = bundle / "site" / "index.html"
    _write(page, page.read_text().replace("</main>", "<p>Johnson &amp; Johnson</p></main>"))
    assert only(release_problems(bundle, held), ": real ") == [
        f"packets/{PACKET}.zip!answer-sheet.json: real ticker 'JNJ'",
        "site/index.html: real name 'Johnson & Johnson'",
    ]


def test_a_price_without_the_synthetic_label_fails(bundle: Path, held: HeldMaterial) -> None:
    prices = bundle / "book" / "securities" / "prices_synthetic.csv"
    _write(prices, prices.read_text().replace(",synthetic,", ",,", 1))
    assert only(release_problems(bundle, held), "label") == [
        "book/securities/prices_synthetic.csv line 2: a price without the 'synthetic' label"
    ]


def test_a_private_task_file_fails(bundle: Path, held: HeldMaterial) -> None:
    _write(bundle / "keys" / "X-PRV-01.json", json_text({"notice": NOTICE, "task_id": "X-PRV-01"}))
    assert only(release_problems(bundle, held), "private task") == [
        "keys/X-PRV-01.json: its path names private task X-PRV-01",
        "keys/X-PRV-01.json: it is private task X-PRV-01's (its task_id)",
    ]


# 5. A filled-form page with no watermark, wherever it sits, not only under returns/.


def test_an_unstamped_filled_form_fails_wherever_it_sits(bundle: Path, held: HeldMaterial) -> None:
    _write(bundle / "site" / "data" / "form.pdf", BLANK_FORM.read_bytes())
    # A filled return flattened has no form: under returns/ it is still held to the watermark, and anywhere but the
    # book's documents and returns it is refused (B-S5).
    flattened = _pdf(f"Form 1040, filled. {NOTICE}")
    _write(bundle / "audit" / "returns" / "f1040.pdf", flattened)
    _write(bundle / "audit" / "export.pdf", flattened)
    problems = release_problems(bundle, held)
    assert "site/data/form.pdf: page 1 has no 'UNREVIEWED' watermark" in problems
    assert "site/data/form.pdf: page 1 does not carry the notice" in problems
    assert only(problems, "watermark", "PDF") == [
        "audit/returns/f1040.pdf: page 1 has no 'UNREVIEWED' watermark",
        "site/data/form.pdf: page 1 has no 'UNREVIEWED' watermark",
        "site/data/form.pdf: page 2 has no 'UNREVIEWED' watermark",
        "audit/export.pdf: a PDF outside the book's documents/ and sealed returns/",
        "audit/returns/f1040.pdf: a PDF outside the book's documents/ and sealed returns/",
        "site/data/form.pdf: a PDF outside the book's documents/ and sealed returns/",
    ]


# 6. A file with no notice (choice 2).


def test_a_document_pdfs_drawn_footer_is_its_notice(clean: Path) -> None:
    # pypdf reads the footer's lines out of order, so the notice is not one run of text in these pages; the clean
    # bundle passes on the footer's lines alone.
    pdfs = sorted((clean / "book" / "households").rglob("documents/*.pdf"))
    assert any(not contains_notice(t) for p in pdfs for t in pdf_pages_text(p.read_bytes()))


def test_a_page_markdown_transcript_or_pdf_without_the_notice_fails(bundle: Path, held: HeldMaterial) -> None:
    page = bundle / "site" / "errata.html"
    _write(page, page.read_text().replace("UNVALIDATED SYNTHETIC RESEARCH PREVIEW.", ""))
    _write(bundle / "audit" / "AUDIT.md", (PUBLISHED / "audit" / "AUDIT.md").read_text())
    transcript = sorted((bundle / "runs" / OPEN_TASK).glob("*.transcript.jsonl"))[0]
    lines = transcript.read_text().splitlines()
    _write(transcript, "\n".join([*lines[1:], lines[0]]) + "\n")
    _write(bundle / "book" / "households" / PACKET / "documents" / "extra.pdf", _pdf("A statement with no footer"))
    missing = "no notice, and no metadata.json or NOTICE.txt with it where it ships"
    assert only(release_problems(bundle, held), "notice") == [
        f"audit/AUDIT.md: {missing}",
        f"book/households/{PACKET}/documents/extra.pdf: page 1 without the notice",
        f"runs/{OPEN_TASK}/{transcript.name}: {missing}",
        f"site/errata.html: {missing}",
    ]


def test_release_json_without_a_top_level_notice_fails(bundle: Path, held: HeldMaterial) -> None:
    names = ["errata.json", "freeze.json", f"keys/{OPEN_TASK}.json", "release.json"]
    for name in names:
        data = json.loads((bundle / name).read_text())
        _write(bundle / name, json_text({k: v for k, v in data.items() if k != "notice"}))
    assert only(release_problems(bundle, held), "notice") == [f"{name}: no top-level notice" for name in names]


def test_a_folder_without_its_notice_file_fails(bundle: Path, held: HeldMaterial, book: Path) -> None:
    # The bundle's own NOTICE.txt covers only the files beside it (the licences), not a folder below it.
    _write(bundle / "audit" / "NOTICE.txt", "Notes.\n")
    (bundle / "site" / "NOTICE.txt").unlink()
    files = read_zip(_packet(book, PACKET))
    del files["NOTICE.txt"]
    _write(bundle / "packets" / f"{PACKET}.zip", write_zip(files))
    missing = "no notice, and no metadata.json or NOTICE.txt with it where it ships"
    assert only(release_problems(bundle, held), "notice") == [
        f"packets/{PACKET}.zip: no NOTICE.txt with the notice at its root",
        f"audit/NOTICE.txt: {missing}",
        f"audit/audit-log.csv: {missing}",
        f"site/static/style.css: {missing}",
    ]


def test_an_unreadable_zip_fails(bundle: Path, held: HeldMaterial) -> None:
    _write(bundle / "packets" / "HH-7350.zip", b"not a zip")
    assert only(release_problems(bundle, held), "HH-7350.zip") == [
        "packets/HH-7350.zip: an unreadable zip (not a zip (File is not a zip file))"
    ]


# 7. A result with no tool, version, model or date.


def test_a_result_without_its_tool_version_model_or_date_fails(bundle: Path, held: HeldMaterial) -> None:
    records = sorted((bundle / "runs" / OPEN_TASK).glob("*.json"))
    blanks = [("cli_version", ""), ("models_reported", []), ("started_utc", None)]
    for record, (field, blank) in zip(records, blanks, strict=False):
        _write(record, json_text({**json.loads(record.read_text()), field: blank}))
    outcomes = bundle / "results" / "private-outcomes.json"
    data = json.loads(outcomes.read_text())
    data["run_sets"][0]["models"] = []
    _write(outcomes, json_text(data))
    problems = release_problems(bundle, held)
    assert only(problems, "lacks") == [
        f"runs/{OPEN_TASK}/{records[0].name} lacks the tool (cli_version), the version (cli_version), "
        "so it cannot be published",
        f"runs/{OPEN_TASK}/{records[1].name} lacks models_reported, so it cannot be published",
        f"runs/{OPEN_TASK}/{records[2].name} lacks started_utc, so it cannot be published",
    ]
    assert only(problems, "results/private-outcomes.json")


# 8. Anything from out/real/.


def test_anything_from_the_real_ticker_build_fails(bundle: Path, held: HeldMaterial, real_book: Path) -> None:
    _write(
        bundle / "site" / "data" / "positions.csv",
        (real_book / f"households/{PACKET}/custodian/positions.csv").read_bytes(),
    )
    _write(bundle / "book" / "metadata.json", (real_book / "metadata.json").read_bytes())
    record = sorted((bundle / "runs" / OPEN_TASK).glob("*.json"))[0]
    _write(record, json_text({**json.loads(record.read_text()), "state": "graded"}))
    problems = release_problems(bundle, held)
    assert "site/data/positions.csv: a file of the real-ticker build (out/real/)" in problems
    assert "book/metadata.json: the metadata of a build whose securities are 'real tickers', not 'aliases'" in problems
    assert (
        f"runs/{OPEN_TASK}/{record.name}: an unmapped run record (state 'graded'), which stays under $CASEBOOK_PRIVATE"
        in problems
    )


# 9. A home-folder path (choice 5a); the same words inside a URL are not one.


def test_a_home_folder_path_fails(bundle: Path, held: HeldMaterial) -> None:
    records = sorted((bundle / "runs" / OPEN_TASK).glob("*.json"))
    homes = ["/Users/someone/casebook", "/home/someone/casebook", "C:\\Users\\someone\\casebook"]
    for record, home in zip(records, homes, strict=False):
        _write(record, json_text({**json.loads(record.read_text()), "book": f"{home}/out/real/0.0.1"}))
    page = bundle / "site" / "index.html"
    _write(page, page.read_text().replace("</main>", "<p>https://example.org/home/page/</p></main>"))
    assert only(release_problems(bundle, held), "home-folder") == [
        f"runs/{OPEN_TASK}/{records[0].name}: a home-folder path ('/Users/someone/')",
        f"runs/{OPEN_TASK}/{records[1].name}: a home-folder path ('/home/someone/')",
        f"runs/{OPEN_TASK}/{records[2].name}: a home-folder path ('C:\\\\\\\\Users\\\\\\\\')",
    ]


# 10. A run record wherever it sits (A-S2, B-S3).


def test_a_run_record_outside_the_run_folders_fails_and_is_held_to_their_checks(
    bundle: Path, held: HeldMaterial
) -> None:
    held_record = json.loads(sorted((bundle / "runs" / HELD_TASK).glob("*.json"))[0].read_text())
    _write(bundle / "audit" / "held-result.json", json_text({**held_record, "grade": {"score": 100}}))
    open_record = json.loads(sorted((bundle / "runs" / OPEN_TASK).glob("*.json"))[0].read_text())
    unnamed = json_text({**open_record, "cli_version": ""}).encode()
    _write(bundle / "audit" / "export.zip", write_zip({"NOTICE.txt": NOTICE_TEXT.encode(), "record.json": unnamed}))
    outside = "a run record outside runs/ and site/data/runs/"
    assert only(release_problems(bundle, held), "run record", "lacks") == [
        f"audit/export.zip!record.json: {outside}",
        "audit/export.zip!record.json lacks the tool (cli_version), the version (cli_version), "
        "so it cannot be published",
        f"audit/held-result.json: {outside}",
        "audit/held-result.json: a held task's run record carries its grade",
    ]


def test_a_run_record_nested_in_another_file_is_held_to_their_checks(bundle: Path, held: HeldMaterial) -> None:
    """Reviewer B, slice 16 round 2, S3: an open task's published key with a graded held record under an extra
    field, and an unnamed record in a list, passed every gate."""
    held_record = json.loads(sorted((bundle / "runs" / HELD_TASK).glob("*.json"))[0].read_text())
    open_record = json.loads(sorted((bundle / "runs" / OPEN_TASK).glob("*.json"))[0].read_text())
    key = bundle / "keys" / f"{OPEN_TASK}.json"
    nested = {
        **json.loads(key.read_text()),
        "debug_run": {**held_record, "grade": {"score": 100}},
        "debug_runs": [{**open_record, "cli_version": ""}],
    }
    _write(key, json_text(nested))
    name = f"keys/{OPEN_TASK}.json"
    problems = only(release_problems(bundle, held), "run record", "lacks")
    assert f"{name}: a run record outside runs/ and site/data/runs/" in problems
    assert f"{name}: a held task's run record carries its grade" in problems
    assert any(p.startswith(f"{name} lacks the tool (cli_version)") for p in problems)


# 11. A file the release does not put where it sits (A-S2, B-S3 to B-S6).


def test_a_file_the_release_does_not_put_there_fails(bundle: Path, held: HeldMaterial, book: Path) -> None:
    _write(bundle / "audit" / "notes.txt", NOTICE_TEXT)
    _write(bundle / "notes.txt", NOTICE_TEXT)
    _write(bundle / "site" / "data" / "notes.txt", NOTICE_TEXT)
    _write(bundle / "keys" / "T-XYZ-99.json", json_text({"notice": NOTICE}))
    _write(bundle / "runs" / OPEN_TASK / "notes.txt", NOTICE_TEXT)
    # A sealed file changed under the old manifest (B-S6): the site's copy is still the book's as built.
    events = "sealed/HH-7350/events.json"
    _write(bundle / "book" / events, (book / events).read_text().replace("-1855.93", "1.00"))
    # A case packet for a household that is not featured, and a featured one's with files a packet never holds.
    _write(bundle / "packets" / "HH-0001.zip", _packet(book, PACKET))
    extra = {"keys/T-REC-01.json": b"{}", f"households/{PACKET}/notes.txt": NOTICE_TEXT.encode()}
    packet = _packet(book, PACKET, extra)
    _write(bundle / "packets" / f"{PACKET}.zip", packet)
    _write(bundle / "site" / "packets" / f"{PACKET}.zip", packet)
    assert only(release_problems(bundle, held), "not ", "listed") == [
        f"book/{events}: not the bytes the book's manifest lists for {events}",
        f"runs/{OPEN_TASK}/notes.txt: not <task>/<run id>.json or <task>/<run id>.transcript.jsonl",
        "audit/notes.txt: not a file the release puts there",
        "keys/T-XYZ-99.json: not the key of a public task that is not held",
        "notes.txt: not a file the release puts at its root",
        "packets/HH-0001.zip: not a featured household's case packet",
        f"packets/{PACKET}.zip!households/{PACKET}/notes.txt: not a file a case packet holds",
        f"packets/{PACKET}.zip!keys/T-REC-01.json: not a file a case packet holds",
        f"site/data/{VERSION}/{events}: not the release's book/{events}",
        "site/data/notes.txt: not a file the release puts in site/",
    ]


# 12. The README's images (A-D2): an SVG is read as text; a PNG ships only as a committed screenshot.


def test_the_readme_images_are_read_or_known_by_their_bytes(bundle: Path, held: HeldMaterial) -> None:
    images = bundle / "docs" / "images"
    _write(images / "site-home.png", (IMAGES / "task-arms.png").read_bytes())
    _write(bundle / "site" / "static" / "results-page.png", (IMAGES / "results-page.png").read_bytes())
    chart = images / "results-chart.svg"
    drawn = "<text>Overall score: 87</text><text>Johnson &amp; Johnson</text><text>/Users/someone/casebook</text>"
    _write(chart, chart.read_text().replace("</svg>", drawn + "</svg>"))
    assert only(release_problems(bundle, held), "results-chart.svg", ".png") == [
        "docs/images/results-chart.svg: shows a combined score",
        "docs/images/results-chart.svg: a home-folder path ('/Users/someone/')",
        "docs/images/site-home.png: not the committed docs/images/site-home.png",
        "docs/images/results-chart.svg: real name 'Johnson & Johnson'",
        "site-home.png: no way to read this file's text, so it cannot be published",
        "results-page.png: no way to read this file's text, so it cannot be published",
    ]
