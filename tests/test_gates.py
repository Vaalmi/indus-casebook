import json
import re
import shutil
from pathlib import Path

import pytest

from casebook.cli import main
from casebook.notice import NOTICE, contains_notice
from casebook.publish import site_build
from casebook.publish.gates import real_identifier_problems, run_gates, synthetic_problems
from casebook.publish.site_build import SiteBuildError, build_site

from .conftest import README


def test_the_built_site_passes_every_gate(site: Path) -> None:
    assert run_gates(site, README, site / "data" / "0.0.1" / "metadata.json") == []


def test_the_readme_carries_the_notice() -> None:
    assert contains_notice(README.read_text())


def test_removing_the_notice_from_the_readme_fails_the_build(book: Path, tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(README.read_text().replace("No performance claims are established.", ""))
    with pytest.raises(SiteBuildError, match=re.escape("README.md lacks the notice")):
        build_site(book, tmp_path / "site", readme)


def test_removing_the_notice_from_a_page_fails_the_build(
    book: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = site_build.render_site

    def without_notice(book_root: Path, *rest: Path | None) -> dict[str, str]:
        pages = real(book_root, *rest)
        page = pages["households/HH-7350.html"]
        start, end = page.index("<aside"), page.index("</aside>") + len("</aside>")
        pages["households/HH-7350.html"] = page[:start] + page[end:]
        return pages

    monkeypatch.setattr(site_build, "render_site", without_notice)
    with pytest.raises(SiteBuildError, match=re.escape("households/HH-7350.html lacks the notice")):
        build_site(book, tmp_path / "site", README)
    assert not (tmp_path / "site").exists()


def test_removing_the_notice_from_the_data_metadata_fails_the_build(book_copy: Path, tmp_path: Path) -> None:
    path = book_copy / "metadata.json"
    metadata = json.loads(path.read_text())
    metadata["notice"] = NOTICE.split(".")[0]
    path.write_text(json.dumps(metadata))
    with pytest.raises(SiteBuildError, match=re.escape("metadata.json lacks the notice")):
        build_site(book_copy, tmp_path / "site", README)


def test_a_price_file_without_the_synthetic_label_fails_the_build(book_copy: Path, tmp_path: Path) -> None:
    path = book_copy / "securities" / "prices_synthetic.csv"
    path.write_text(path.read_text().replace("synthetic", "invented"))
    with pytest.raises(SiteBuildError) as raised:
        build_site(book_copy, tmp_path / "site", README)
    assert "securities/prices_synthetic.csv line 2: a price without the 'synthetic' label" in str(raised.value)
    assert "securities/prices_synthetic.csv: shows prices without the word 'synthetic'" in str(raised.value)


def test_a_json_price_without_the_synthetic_label_fails_the_build(book_copy: Path, tmp_path: Path) -> None:
    # Reviewer A, slice 1 round 1, S2: portfolio/positions.json carries prices and was not checked.
    path = book_copy / "households" / "HH-4821" / "portfolio" / "positions.json"
    path.write_text(path.read_text().replace("synthetic", "invented"))
    with pytest.raises(SiteBuildError) as raised:
        build_site(book_copy, tmp_path / "site", README)
    assert "households/HH-4821/portfolio/positions.json.positions[0]: a price without the 'synthetic' label" in str(
        raised.value
    )


def test_a_pdf_showing_prices_without_the_word_synthetic_fails(tmp_path: Path) -> None:
    from reportlab.pdfgen.canvas import Canvas

    canvas = Canvas(str(tmp_path / "statement.pdf"), invariant=1)
    canvas.drawString(72, 720, "Price 41.20 per unit")
    canvas.save()
    assert synthetic_problems(tmp_path) == ["statement.pdf: shows prices without the word 'synthetic'"]


@pytest.mark.parametrize(
    ("planted", "found"),
    [
        ("<p>Trim the MSFT position</p>", "real ticker 'MSFT'"),
        ("<p>Microsoft Corporation</p>", "real name 'Microsoft'"),
    ],
)
def test_a_real_ticker_or_name_planted_in_a_page_fails_the_build(
    book: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, planted: str, found: str
) -> None:
    real = site_build.render_site

    def with_leak(book_root: Path, *rest: Path | None) -> dict[str, str]:
        pages = real(book_root, *rest)
        pages["index.html"] = pages["index.html"].replace("</main>", planted + "</main>")
        return pages

    monkeypatch.setattr(site_build, "render_site", with_leak)
    with pytest.raises(SiteBuildError, match=re.escape(f"index.html: {found}")):
        build_site(book, tmp_path / "site", README)


def test_a_real_ticker_in_a_published_data_file_fails_the_build(book_copy: Path, tmp_path: Path) -> None:
    path = book_copy / "households" / "HH-4821" / "custodian" / "accounts.csv"
    path.write_text(path.read_text().replace("Joint tenants", "JNJ tenants", 1))
    with pytest.raises(SiteBuildError, match=re.escape("accounts.csv: real ticker 'JNJ'")):
        build_site(book_copy, tmp_path / "site", README)


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("page.html", "<p>Johnson &amp; Johnson</p>"),
        ("page.html", '<a title="Microsoft&#32;Corp">x</a>'),
        ("data.json", '{"note": "Johnson \\u0026 Johnson"}'),
        # Reviewer B, slice 1 round 2, S1 held: a tag inside the name split it.
        ("page.html", "<p>Johnson &amp; <strong>Johnson</strong></p>"),
        ("page.html", "<p><b>Micro</b>soft</p>"),
        ("page.html", "<td>Johnson &amp;</td><td>Johnson</td>"),
        ("page.html", "<p>Vanguard\n   Total Bond Market</p>"),
        ("page.html", "<td>MSFT</td><td>40</td>"),
    ],
)
def test_an_escaped_real_name_is_still_a_leak(tmp_path: Path, name: str, content: str) -> None:
    (tmp_path / name).write_text(content)
    assert real_identifier_problems(tmp_path) != []


def test_a_ticker_inside_a_longer_word_is_not_a_leak(tmp_path: Path) -> None:
    (tmp_path / "page.html").write_text("<p>BNDX MSFTs XJNJ</p>")
    assert real_identifier_problems(tmp_path) == []


def test_a_file_the_gates_cannot_read_fails_the_build(site: Path, tmp_path: Path) -> None:
    copy = tmp_path / "site"
    shutil.copytree(site, copy)
    (copy / "static" / "logo.png").write_bytes(b"\x89PNG")
    problems = run_gates(copy, README, copy / "data" / "0.0.1" / "metadata.json")
    assert problems == ["logo.png: no way to read this file's text, so it cannot be published"]


def test_a_household_that_fails_a_check_is_never_published(book_copy: Path, tmp_path: Path) -> None:
    (book_copy / "households" / "HH-7350" / "custodian" / "positions.csv").write_text(
        "account_id,security_id,security,units,price,price_label,market_value,valuation_date,known_as_of\n"
    )
    with pytest.raises(SiteBuildError, match="failed their checks and cannot be published: HH-7350"):
        build_site(book_copy, tmp_path / "site", README)


def test_the_site_command_reports_a_failed_gate(book: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("# No notice here\n")
    assert main(["site", "--book", str(book), "--out", str(tmp_path / "site"), "--readme", str(readme)]) == 1
    assert "README.md lacks the notice" in capsys.readouterr().err


def test_a_real_ticker_inside_an_embedded_pdf_is_a_leak_and_mapping_omits_it(tmp_path: Path) -> None:
    # Reviewers A and B, slice 2 round 2, new: transcripts carried statement PDFs as base64.
    import base64
    import io

    from reportlab.pdfgen.canvas import Canvas

    from casebook.publish.mapper import OMITTED, map_to_aliases

    buffer = io.BytesIO()
    canvas = Canvas(buffer, invariant=1)
    canvas.drawString(72, 720, "Holdings: 891 VTI at 336.56 synthetic")
    canvas.save()
    blob = base64.b64encode(buffer.getvalue()).decode()
    line = {"tool_use_result": {"file": {"base64": blob}}, "message": {"content": [{"source": {"data": blob}}]}}
    (tmp_path / "run.transcript.jsonl").write_text(json.dumps(line) + "\n")
    assert real_identifier_problems(tmp_path) == ["run.transcript.jsonl: real ticker 'VTI'"]
    mapped = map_to_aliases(line)
    assert mapped["tool_use_result"]["file"]["base64"] == OMITTED
    assert mapped["message"]["content"][0]["source"]["data"] == OMITTED
