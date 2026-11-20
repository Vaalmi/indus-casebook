"""The preview release's gates (docs/PLAN.md, slice 16, criterion 1): each refusal planted into a small real bundle
built from the book fixture and the committed published files, and the clean bundle passing."""

import io
import json
import os
import shutil
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
def held(book: Path, real_book: Path, held_keys: Path) -> HeldMaterial:
    return held_material(book, real_book, TASKS, held_keys)


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


def test_the_held_material_is_the_held_tasks_keys_and_tax_summaries(held: HeldMaterial) -> None:
    # 17 of the 24 public tasks are held (review/slice16-contract.md; docs/STATUS.md, slice 14).
    assert len(held.tasks) == 17
    assert {"T-TAX-01", "T-TAX-06", "T-REC-03", "T-MTG-01", "T-CMP-01"} <= held.tasks.keys()
    assert {"T-REC-01", "T-REC-02", "T-CMP-05"}.isdisjoint(held.tasks)
    assert held.real_only


# 1. A tax or RMD answer key, a tax answer sheet, or a verdict on a tax-lot or RMD task.


def test_a_held_key_fails_by_its_bytes_its_content_or_its_place(
    bundle: Path, held: HeldMaterial, held_keys: Path, book: Path
) -> None:
    key_file = held_keys / VERSION / f"{HELD_TASK}.json"
    _write(bundle / "site" / "data" / "extra.json", key_file.read_bytes())
    _write(bundle / "keys" / f"{HELD_TASK}.json", _noticed(key_file))
    sheet = {
        "notice": NOTICE,
        "household_id": PACKET,
        "keys": [{"task_id": HELD_TASK, "key": json.loads(key_file.read_text())}],
    }
    _write(
        bundle / "packets" / f"{PACKET}.zip", _packet(book, PACKET, {"answer-sheet.json": json_text(sheet).encode()})
    )
    assert only(release_problems(bundle, held), "held task's answer key", "key of held task") == [
        f"keys/{HELD_TASK}.json: holds a held task's answer key or a tax answer sheet",
        f"packets/{PACKET}.zip!answer-sheet.json: holds a held task's answer key or a tax answer sheet",
        "site/data/extra.json: a held task's answer key or a tax answer sheet",
        "site/data/extra.json: holds a held task's answer key or a tax answer sheet",
        f"keys/{HELD_TASK}.json: the key of held task {HELD_TASK}",
    ]


def test_a_tax_summary_fails(bundle: Path, held: HeldMaterial, book: Path) -> None:
    summary = "sealed/HH-5271/tax_summary.json"
    _write(bundle / "book" / summary, (book / summary).read_bytes())
    assert only(release_problems(bundle, held), "tax_summary") == [
        f"book/{summary}: a held task's answer key or a tax answer sheet",
        f"book/{summary}: a tax summary, a tax answer sheet held until the tax review",
        f"book/{summary}: holds a held task's answer key or a tax answer sheet",
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
    shown = {
        "results.html": "<p>Combined score: 87</p>",
        "index.html": "<table><tr><td>Overall score</td><td>92.5</td></tr></table>",
        "errata.html": "<p>71% overall score</p>",
    }
    for name, html in shown.items():
        page = bundle / "site" / name
        _write(page, page.read_text().replace("</main>", html + "</main>"))
    assert only(release_problems(bundle, held), "combined score") == [
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
    assert only(release_problems(bundle, held), "HH-7350") == [
        "book/households/HH-7350: fails its checks",
        "book/households/HH-7350/custodian/positions.csv: not the checked book's "
        "households/HH-7350/custodian/positions.csv",
    ]


def test_a_household_the_checked_book_does_not_hold_fails(bundle: Path, held: HeldMaterial, book: Path) -> None:
    accounts = f"households/{PACKET}/custodian/accounts.csv"
    _write(bundle / "book" / "households" / "HH-0001" / "custodian" / "accounts.csv", (book / accounts).read_bytes())
    changed = (book / accounts).read_text().replace("joint_taxable", "individual_taxable", 1).encode()
    _write(bundle / "packets" / f"{PACKET}.zip", _packet(book, PACKET, {accounts: changed}))
    assert only(release_problems(bundle, held), "HH-0001", "checked book") == [
        f"packets/{PACKET}.zip!{accounts}: not the checked book's {accounts}",
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
    problems = only(release_problems(bundle, held), "form.pdf")
    assert "site/data/form.pdf: page 1 has no 'UNREVIEWED' watermark" in problems
    assert "site/data/form.pdf: page 1 does not carry the notice" in problems


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
    out = io.BytesIO()
    SimpleDocTemplate(out).build([Paragraph("A statement with no footer", getSampleStyleSheet()["Normal"])])
    _write(bundle / "book" / "households" / PACKET / "documents" / "extra.pdf", out.getvalue())
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
