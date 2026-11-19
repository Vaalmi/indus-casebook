"""docs/PLAN.md, slice 15: the plugin ships the sample book, "the 20 featured households as packaged in the plugin"
(docs/SPEC.md, Words), under aliases only, with the four source sets and the manifest and no sealed file (the
owner's decision of 19 November 2026, docs/decisions/2026-11-19-plugin-gate.md)."""

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

import casebook.model.archetypes
from casebook.cli import main
from casebook.notice import NOTICE
from casebook.publish.sample_book import SampleBookError, build_sample_book, sample_book_problems

from .conftest import FEATURED, ROOT

COMMITTED = ROOT / "plugin" / "book"
# A private task's ID, built so that no public file states one (as in tests/test_private_set.py).
PRIVATE_ID = "X-" + "REC-09"
TOP_LEVEL = {
    "manifest.json",
    "metadata.json",
    "NOTICE.txt",
    "securities/securities.csv",
    "securities/prices_synthetic.csv",
}


def tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def sample(book: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("plugin") / "book"
    build_sample_book(book, out)
    return out


@pytest.fixture
def sample_copy(sample: Path, tmp_path: Path) -> Path:
    copy = tmp_path / "book"
    shutil.copytree(sample, copy)
    return copy


def test_the_sample_book_holds_the_20_featured_households_four_source_sets_and_nothing_else(
    book: Path, sample: Path
) -> None:
    assert len(FEATURED) == 20
    assert sorted(p.name for p in (sample / "households").iterdir()) == list(FEATURED)
    book_manifest = json.loads((book / "manifest.json").read_text())
    expected = TOP_LEVEL | {
        name for name in book_manifest["files"] if name.split("/")[:2] in (["households", h] for h in FEATURED)
    }
    assert set(tree(sample)) == expected
    for name in expected - {"manifest.json", "metadata.json", "NOTICE.txt"}:
        assert (sample / name).read_bytes() == (book / name).read_bytes(), name
    for name in tree(sample):
        parts = name.split("/")
        assert parts[0] != "sealed" and parts[-1] != "tax_summary.json", name
        if parts[0] == "households":
            assert parts[2] in ("crm", "custodian", "portfolio", "documents"), name


def test_its_manifest_lists_the_featured_entries_and_every_file_s_hash(book: Path, sample: Path) -> None:
    book_manifest = json.loads((book / "manifest.json").read_text())
    manifest = json.loads((sample / "manifest.json").read_text())
    assert manifest["version"] == "0.0.1" and manifest["seed"] == 2026
    assert manifest["households"] == [h for h in book_manifest["households"] if h["household_id"] in FEATURED]
    assert [h["household_id"] for h in manifest["households"]] == list(FEATURED)
    on_disk = tree(sample)
    assert list(manifest["files"]) == sorted(set(on_disk) - {"manifest.json"})
    for name, digest in manifest["files"].items():
        assert hashlib.sha256(on_disk[name]).hexdigest() == digest, name
        if name != "metadata.json" and name in book_manifest["files"]:
            assert digest == book_manifest["files"][name], name


def test_its_metadata_is_the_book_s_under_the_sample_book_s_title_and_it_carries_the_notice(
    book: Path, sample: Path
) -> None:
    metadata = json.loads((sample / "metadata.json").read_text())
    assert metadata == json.loads((book / "metadata.json").read_text()) | {"title": "The Indus Casebook: sample book"}
    assert metadata["notice"] == NOTICE
    assert metadata["securities"] == "aliases"
    assert (sample / "NOTICE.txt").read_text() == NOTICE + "\n"
    # Written the way the book writes JSON: sorted keys, two-space indent, a final newline.
    assert (sample / "metadata.json").read_text() == json.dumps(metadata, sort_keys=True, indent=2) + "\n"


def test_the_finished_sample_book_passes_its_gates(sample: Path) -> None:
    assert sample_book_problems(sample, len(FEATURED)) == []


def test_a_rebuild_is_byte_identical(book: Path, sample: Path, tmp_path: Path) -> None:
    again = tmp_path / "plugin" / "book"
    build_sample_book(book, again)
    assert tree(again) == tree(sample)


def test_the_committed_plugin_book_is_current(sample: Path) -> None:
    """`plugin/book/` is committed, so installing the plugin from the repo ships it. The featured-only `book`
    fixture gives the same bytes as a full build for these files (the featured households' files, the
    securities and the metadata), so it stands in for `casebook build --seed 2026`."""
    committed, fresh = tree(COMMITTED), tree(sample)
    assert sorted(committed) == sorted(fresh), "run `uv run casebook sample-book` and commit plugin/book/"
    stale = [name for name in fresh if committed[name] != fresh[name]]
    assert stale == [], "run `uv run casebook sample-book` and commit plugin/book/"


def test_a_build_replaces_the_output_and_leaves_no_staging_folder(book: Path, sample: Path, tmp_path: Path) -> None:
    out = tmp_path / "plugin" / "book"
    out.mkdir(parents=True)
    (out / "stale.txt").write_text("from an earlier build\n")
    build_sample_book(book, out)
    assert tree(out) == tree(sample)
    assert sorted(p.name for p in (tmp_path / "plugin").iterdir()) == ["book"]


# The build's refusals, each naming why.


def test_a_real_ticker_build_is_refused(book_copy: Path, tmp_path: Path) -> None:
    path = book_copy / "metadata.json"
    path.write_text(json.dumps(json.loads(path.read_text()) | {"securities": "real tickers"}))
    with pytest.raises(SampleBookError, match="is not a default build"):
        build_sample_book(book_copy, tmp_path / "plugin" / "book")


def test_held_out_featured_households_are_refused_before_the_freeze(
    book: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(casebook.model.archetypes, "FREEZE_RECORD", tmp_path / "no-freeze.json")
    with pytest.raises(SampleBookError, match="held out until the freeze") as raised:
        build_sample_book(book, tmp_path / "plugin" / "book")
    sealed = json.loads((book / "sealed" / "households.json").read_text())["households"]
    held = sorted(h["household_id"] for h in sealed if h["set"] == "featured" and h["archetype"] in (7, 8))
    assert len(held) == 4
    assert str(raised.value).startswith(", ".join(held))
    assert not (tmp_path / "plugin" / "book").exists()


def test_a_book_that_fails_a_check_is_refused(book_copy: Path, tmp_path: Path) -> None:
    (book_copy / "households" / "HH-7350" / "custodian" / "positions.csv").write_text(
        "account_id,security_id,security,units,price,price_label,market_value,valuation_date,known_as_of\n"
    )
    with pytest.raises(SampleBookError, match="failed their checks and cannot be packaged: HH-7350"):
        build_sample_book(book_copy, tmp_path / "plugin" / "book")


def test_a_gate_failure_keeps_the_output_as_it_was(book_copy: Path, sample: Path, tmp_path: Path) -> None:
    # The account type, which no other source repeats, so no check catches it and only the alias gate can.
    path = book_copy / "households" / "HH-4821" / "custodian" / "accounts.csv"
    path.write_text(path.read_text().replace("joint_taxable", "JNJ", 1))
    out = tmp_path / "plugin" / "book"
    shutil.copytree(sample, out)
    with pytest.raises(SampleBookError) as raised:
        build_sample_book(book_copy, out)
    assert "households/HH-4821/custodian/accounts.csv: real ticker 'JNJ'" in str(raised.value)
    # Its bytes are no longer the ones the book's manifest gives.
    assert "households/HH-4821/custodian/accounts.csv: its hash is not the one the manifest gives" in str(raised.value)
    assert tree(out) == tree(sample)
    assert sorted(p.name for p in (tmp_path / "plugin").iterdir()) == ["book"]


# The gates on a finished sample book, one by one.


def test_a_price_without_the_synthetic_label_fails(sample_copy: Path) -> None:
    path = sample_copy / "securities" / "prices_synthetic.csv"
    path.write_text(path.read_text().replace("synthetic", "invented"))
    problems = sample_book_problems(sample_copy, len(FEATURED))
    assert "securities/prices_synthetic.csv line 2: a price without the 'synthetic' label" in problems


def test_a_real_ticker_fails(sample_copy: Path) -> None:
    path = sample_copy / "households" / "HH-4821" / "custodian" / "accounts.csv"
    path.write_text(path.read_text().replace("joint_taxable", "JNJ", 1))
    problems = sample_book_problems(sample_copy, len(FEATURED))
    assert "households/HH-4821/custodian/accounts.csv: real ticker 'JNJ'" in problems


def test_anything_of_the_private_set_fails(sample_copy: Path) -> None:
    (sample_copy / "households" / "HH-4821" / "crm" / "task.json").write_text(json.dumps({"task_id": PRIVATE_ID}))
    problems = sample_book_problems(sample_copy, len(FEATURED))
    assert f"households/HH-4821/crm/task.json: it is private task {PRIVATE_ID}'s (its task_id)" in problems


@pytest.mark.parametrize(
    "name",
    ["sealed/HH-4821/tax_summary.json", "sealed/registry.json", "households/HH-4821/portfolio/tax_summary.json"],
)
def test_a_sealed_or_tax_summary_file_fails(sample_copy: Path, name: str) -> None:
    path = sample_copy / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n")
    problems = sample_book_problems(sample_copy, len(FEATURED))
    assert f"{name}: a sealed file, which the sample book never holds" in problems


def test_a_household_not_in_the_manifest_fails(sample_copy: Path) -> None:
    # HH-0190, a background household of the public book.
    shutil.copytree(sample_copy / "households" / "HH-4821", sample_copy / "households" / "HH-0190")
    problems = sample_book_problems(sample_copy, len(FEATURED))
    assert "households/HH-0190: a household not in the sample book's manifest" in problems


def test_a_file_not_in_the_manifest_or_with_a_wrong_hash_fails(sample_copy: Path) -> None:
    (sample_copy / "households" / "HH-4821" / "crm" / "extra.json").write_text("{}\n")
    with (sample_copy / "households" / "HH-7350" / "crm" / "crm.json").open("a") as handle:
        handle.write("\n")
    (sample_copy / "securities" / "securities.csv").unlink()
    problems = sample_book_problems(sample_copy, len(FEATURED))
    assert "households/HH-4821/crm/extra.json: not in the manifest's files" in problems
    assert "households/HH-7350/crm/crm.json: its hash is not the one the manifest gives" in problems
    assert "securities/securities.csv: in the manifest's files but missing" in problems


def test_a_household_count_other_than_the_featured_fails(sample_copy: Path) -> None:
    path = sample_copy / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["households"] = manifest["households"][1:]
    path.write_text(json.dumps(manifest))
    problems = sample_book_problems(sample_copy, len(FEATURED))
    assert "manifest.json lists 19 households; the book has 20 featured" in problems
    assert "households/HH-1204: a household not in the sample book's manifest" in problems


def test_metadata_without_the_notice_fails(sample_copy: Path) -> None:
    path = sample_copy / "metadata.json"
    path.write_text(json.dumps(json.loads(path.read_text()) | {"notice": NOTICE.split(".")[0]}))
    (sample_copy / "NOTICE.txt").write_text("A notice of our own.\n")
    problems = sample_book_problems(sample_copy, len(FEATURED))
    assert "metadata.json lacks the notice" in problems
    assert "NOTICE.txt is not the notice" in problems


# The command.


def test_the_command_writes_the_sample_book(
    book: Path, sample: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "plugin" / "book"
    assert main(["sample-book", "--book", str(book), "--out", str(out)]) == 0
    assert f"wrote the sample book: 20 households, {len(tree(sample))} files, into {out}" in capsys.readouterr().out
    assert tree(out) == tree(sample)


def test_the_command_reports_a_refusal(book_copy: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = book_copy / "metadata.json"
    path.write_text(json.dumps(json.loads(path.read_text()) | {"securities": "real tickers"}))
    assert main(["sample-book", "--book", str(book_copy), "--out", str(tmp_path / "plugin" / "book")]) == 1
    assert re.search(r"sample book failed: .* is not a default build", capsys.readouterr().err)
