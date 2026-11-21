"""The README a builder reads (docs/PLAN.md, slice 16): the notice first; one command each to build the book, check
it and run a task, each in its own bash block; every image it shows committed and well formed; and every
`casebook` command it names a real subcommand."""

import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

from casebook.cli import main
from casebook.notice import contains_notice

from .conftest import README, ROOT

IMAGES = ROOT / "docs" / "images"
# The spec's notice opens the README in its own block, headline in bold (docs/SPEC.md, Rules: "Notice everywhere").
HEADLINE = "> **UNVALIDATED SYNTHETIC RESEARCH PREVIEW.**"
# The slice's criterion: "one command each to build the book, check it and run a task".
BUILD = "uv run casebook build --seed 2026"
CHECK = "uv run casebook check"
RUN = "CASEBOOK_PRIVATE=../indus-casebook-private uv run casebook run --task T-REC-01 --arm skill"
# The images the README is to show: the site's four pages, two drawn diagrams and the results chart.
SHOWN = {
    "site-home.png",
    "household-source-sets.png",
    "household-planted-item.png",
    "task-arms.png",
    "results-page.png",
    "book-made-and-checked.svg",
    "task-run-and-graded.svg",
    "results-chart.svg",
}
LARGEST_PNG = 400 * 1024


def text() -> str:
    return README.read_text(encoding="utf-8")


def bash_blocks() -> list[list[str]]:
    """Each bash block's command lines, comments and blank lines left out."""
    blocks = re.findall(r"^```bash\n(.*?)^```", text(), flags=re.MULTILINE | re.DOTALL)
    return [[line.strip() for line in b.splitlines() if line.strip() and not line.startswith("#")] for b in blocks]


def linked_images() -> list[str]:
    return re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", text()) + re.findall(r'<img[^>]*\ssrc="([^"]+)"', text())


def test_the_notice_is_the_first_block() -> None:
    first = text().split("\n\n", 1)[0]
    assert first.startswith(HEADLINE)
    assert contains_notice(first)


@pytest.mark.parametrize("command", [BUILD, CHECK, RUN, "make setup", "make check"])
def test_each_command_has_a_bash_block_of_its_own(command: str) -> None:
    assert [command] in bash_blocks()


def test_the_run_names_what_it_needs_first() -> None:
    blocks = bash_blocks()
    assert ["uv run casebook build --real-tickers"] in blocks
    assert blocks.index(["uv run casebook build --real-tickers"]) < blocks.index([RUN])
    assert "signed-in `claude` CLI" in text()


def test_every_image_shown_is_committed_and_every_one_is_shown() -> None:
    linked = linked_images()
    assert all(link.startswith("docs/images/") for link in linked)
    assert {Path(link).name for link in linked} == SHOWN
    assert {p.name for p in IMAGES.iterdir() if p.is_file()} == SHOWN
    assert all((ROOT / link).is_file() for link in linked)


@pytest.mark.parametrize("name", sorted(n for n in SHOWN if n.endswith(".svg")))
def test_each_svg_parses_and_draws_its_own_background(name: str) -> None:
    root = ElementTree.parse(IMAGES / name).getroot()
    svg = "{http://www.w3.org/2000/svg}"
    assert root.tag == f"{svg}svg"
    assert root.find(f"{svg}title") is not None
    # A solid background, so the image reads in a dark theme as in a light one.
    background = root.find(f"{svg}rect")
    assert background is not None
    assert background.get("fill") == "#ffffff"
    assert root.findall(f".//{svg}text"), "the words are text, not paths"
    assert root.find(f".//{svg}script") is None


@pytest.mark.parametrize("name", sorted(n for n in SHOWN if n.endswith(".png")))
def test_each_screenshot_is_a_png_of_reasonable_size(name: str) -> None:
    data = (IMAGES / name).read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(data) < LARGEST_PNG


def test_the_results_chart_counts_no_combined_score_and_shows_the_held() -> None:
    chart = (IMAGES / "results-chart.svg").read_text(encoding="utf-8")
    assert "no combined score" in chart
    # The committed pass, named by its tool, model and dates (published/runs, 18 and 19 November 2026).
    assert "Claude Code 2.1.304 · model claude-opus-5-5" in chart
    assert "2026-11-18 to 2026-11-19" in chart
    # Every tax-lot and RMD run is held: 24 tasks' 6 in that workflow, 3 repeats, under each arm.
    assert chart.count(">18 held<") == 3


def subcommands(capsys: pytest.CaptureFixture[str]) -> set[str]:
    with pytest.raises(SystemExit):
        main(["--help"])
    choices = re.search(r"\{([a-z,-]+)\}", capsys.readouterr().out)
    assert choices is not None
    return set(choices.group(1).split(","))


def named_commands() -> set[str]:
    return {m for block in bash_blocks() for line in block for m in re.findall(r"uv run casebook ([a-z-]+)", line)}


def test_the_readme_names_the_commands_it_should() -> None:
    assert {"build", "check", "run", "site", "release"} <= named_commands()


@pytest.mark.parametrize("command", sorted(named_commands()))
def test_each_command_named_is_a_casebook_subcommand(command: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert command in subcommands(capsys)


def test_the_licences_section_names_the_copyright_holder() -> None:
    # The owner, 21 November 2026: the copyright holder is "Vaalmika Platforms Inc.".
    licences = text().split("## Licences", 1)[1]
    assert "Copyright 2026 Vaalmika Platforms Inc." in licences
