"""Draw the README's images into docs/images/, so they can be drawn again.

    uv run python tools/readme_images.py

It builds the default book from seed 2026 and the site from the committed published runs, both into a temporary
folder (the same `casebook build` and `casebook site` a builder runs), and takes four screenshots of the site in
Chromium. It draws two diagrams by hand as SVG, and a chart of the committed results, counted the way the
results page counts them (`casebook.site.results`). Every SVG has a solid background, so it reads in GitHub's
light and dark themes alike.
"""

import argparse
import os
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image
from playwright.sync_api import Page, sync_playwright

from casebook import cli
from casebook.model.files import SEALED_HOUSEHOLDS, read_json
from casebook.notice import NOTICE_HEADLINE
from casebook.site.results import (
    OUTCOME_NAMES,
    OUTCOMES,
    WORKFLOW_NAMES,
    RunSetResult,
    load_private_outcomes,
    private_outcomes_path,
    results,
)
from casebook.site.tasks import ARM_NAMES, ARM_ORDER, is_held, load_records
from casebook.tasks.task import WORKFLOWS, load_task

REPO = Path(__file__).resolve().parents[1]
IMAGES = Path("docs/images")
SEED = "2026"
VIEWPORT = {"width": 1280, "height": 900}
SCALE = 2
# The site's own look (src/casebook/site/static/style.css).
INK = "#1d2329"
MUTED = "#5b6670"
LINE = "#d9dee3"
PAPER = "#ffffff"
PANEL = "#f5f7f9"
ACCENT = "#1f5f8b"
NOTICE_BG = "#fff4d6"
NOTICE_LINE = "#c99a1a"
STOP = "#b3261e"
FONT = 'system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif'
# The chart's outcome colours, checked for colour-blind separation on white (passed, failed, failed run); held is
# a hatched grey, since it is no verdict at all. Every bar also carries its counts in words.
OUTCOME_FILL = {"passed": "#1f6fb2", "failed": "#c43d2b", "failed_run": "#d9a21b", "held": "url(#held)"}


# ---------------------------------------------------------------- screenshots


@dataclass(frozen=True)
class Shot:
    """One screenshot: a page of the site, clipped from the top of one element to the bottom of another."""

    name: str
    page: str
    top: str
    bottom: str
    # Pixels kept above the top element and below the bottom one.
    margin: int = 16
    # Where the clip stops at most, below its top: a column of source files runs on for a long way.
    tallest: int | None = None


SHOTS = (
    Shot("site-home.png", "index.html", ".notice", "section.households tbody tr:nth-child(12)", margin=0),
    Shot("household-source-sets.png", "households/HH-4821.html", ".notice", ".sources", margin=0, tallest=1180),
    Shot(
        "household-planted-item.png",
        "households/HH-4821.html",
        "#planted-heading",
        "section[aria-labelledby=truth-heading] .layer:nth-child(3) .figures",
        tallest=900,
    ),
    Shot("task-arms.png", "tasks/T-REC-01.html", "#arms-heading", "section[aria-labelledby=arms-heading] .layers"),
    Shot(
        "results-page.png",
        "results.html",
        "section[data-run-set]:last-of-type",
        "section[data-run-set]:last-of-type [data-group]",
    ),
)


def _clip(page: Page, shot: Shot) -> dict[str, float]:
    top = page.locator(shot.top).first.bounding_box()
    bottom = page.locator(shot.bottom).first.bounding_box()
    if top is None or bottom is None:
        raise SystemExit(f"{shot.page}: {shot.top} or {shot.bottom} is not on the page")
    y = max(0.0, top["y"] - shot.margin)
    end = bottom["y"] + bottom["height"] + shot.margin
    if shot.tallest is not None:
        end = min(end, y + shot.tallest)
    return {"x": 0, "y": y, "width": VIEWPORT["width"], "height": end - y}


def _optimise(path: Path) -> None:
    """A screenshot of a page is mostly flat colour: 256 colours keep the text crisp at a fraction of the size."""
    with Image.open(path) as image:
        small = image.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    small.save(path, optimize=True)


def screenshots(site: Path, out: Path) -> list[Path]:
    written: list[Path] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(
            viewport={"width": VIEWPORT["width"], "height": VIEWPORT["height"]}, device_scale_factor=SCALE
        )
        page.emulate_media(color_scheme="light")
        for shot in SHOTS:
            page.goto((site / shot.page).as_uri())
            path = out / shot.name
            page.screenshot(path=str(path), clip=_clip(page, shot), full_page=True)  # pyright: ignore[reportArgumentType]
            _optimise(path)
            written.append(path)
        browser.close()
    return written


# ---------------------------------------------------------------- drawing


def _svg(width: int, height: int, title: str, description: str, body: Sequence[str], defs: str = "") -> str:
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" font-family=\'{FONT}\'>',
            f"<title>{escape(title)}</title>",
            f"<desc>{escape(description)}</desc>",
            "<defs>",
            f'<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="{MUTED}"/></marker>',
            defs,
            "</defs>",
            f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="12" fill="{PAPER}" stroke="{LINE}"/>',
            *body,
            "</svg>",
            "",
        ]
    )


def _text(
    x: float, y: float, words: str, size: int = 13, fill: str = INK, weight: str = "normal", anchor: str = "start"
) -> str:
    bold = ' font-weight="700"' if weight == "bold" else ""
    end = f' text-anchor="{anchor}"' if anchor != "start" else ""
    return f'<text x="{x:g}" y="{y:g}" font-size="{size}" fill="{fill}"{bold}{end}>{escape(words)}</text>'


def _box(
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    lines: Sequence[str] = (),
    fill: str = PANEL,
    stroke: str = LINE,
    title_fill: str = INK,
    dashed: bool = False,
) -> list[str]:
    dash = ' stroke-dasharray="6 4"' if dashed else ""
    parts = [f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="8" fill="{fill}" stroke="{stroke}"{dash}/>']
    parts.append(_text(x + 14, y + 24, title, size=15, fill=title_fill, weight="bold"))
    parts += [_text(x + 14, y + 46 + 18 * i, line, fill=MUTED) for i, line in enumerate(lines)]
    return parts


def _arrow(x1: float, y1: float, x2: float, y2: float, label: str = "") -> list[str]:
    parts = [
        f'<path d="M{x1:g} {y1:g} L{x2:g} {y2:g}" stroke="{MUTED}" stroke-width="1.6" fill="none" '
        'marker-end="url(#arrow)"/>'
    ]
    if label:
        parts.append(_text((x1 + x2) / 2, min(y1, y2) - 6, label, size=12, fill=MUTED, anchor="middle"))
    return parts


def _elbow(points: Sequence[tuple[float, float]]) -> str:
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:g} {y:g}" for i, (x, y) in enumerate(points))
    return f'<path d="{path}" stroke="{MUTED}" stroke-width="1.6" fill="none" marker-end="url(#arrow)"/>'


def book_diagram(households: int, featured: int) -> str:
    """How a book is made and checked: seed, households, four source sets, checks, then site, plugin, release."""
    body: list[str] = [
        _text(32, 44, "How a book is made and checked", size=22, weight="bold"),
        _text(
            32,
            70,
            "One seed and one version give byte-identical files. A household that fails a check is never published.",
        ),
    ]
    # The seed and the hand-written inputs.
    body += _box(
        32,
        110,
        180,
        92,
        "Seed 2026",
        ["uv run casebook", "build --seed 2026"],
        fill="#e8f1f8",
        stroke=ACCENT,
        title_fill=ACCENT,
    )
    body += _box(32, 226, 180, 110, "Scripts and ledger", ["book/scripted/", "book/id_ledger.json", "IDs never change"])
    body += _arrow(212, 156, 256, 156)
    body += [_elbow([(212, 281), (234, 281), (234, 170), (256, 170)])]
    # The households.
    body += _box(
        256,
        110,
        236,
        226,
        f"{households} households",
        [
            "10 archetypes, in pairs:",
            "a trap with a planted item,",
            "and its twin: clean, a near",
            "miss or unresolved",
            "",
            f"{featured} featured, {households - featured} background",
            "",
            "History replayed from",
            "1 Jan 2025 to 15 Apr 2026",
        ],
    )
    body += _arrow(492, 223, 536, 223)
    # The four source sets, and the sealed layer beside them.
    sources = (
        ("Custodian", "CSVs: positions, lots, cash"),
        ("Portfolio system", "JSON: IPS, fees, billing"),
        ("CRM", "JSON: contacts, notes"),
        ("Documents", "PDFs: statements, 1099s"),
    )
    body.append(_text(536, 102, "Four source sets per household", size=13, fill=MUTED, weight="bold"))
    for i, (name, what) in enumerate(sources):
        y = 110 + i * 58
        body.append(f'<rect x="536" y="{y}" width="250" height="50" rx="8" fill="{PANEL}" stroke="{LINE}"/>')
        body.append(_text(550, y + 21, name, size=14, weight="bold"))
        body.append(_text(550, y + 40, what, size=12, fill=MUTED))
    body += _box(
        536,
        354,
        250,
        92,
        "Sealed",
        ["event log, registry, tax summary:", "never shown to the AI under test"],
        fill=PAPER,
        dashed=True,
    )
    body += _arrow(786, 223, 830, 223)
    # The checks and the gates.
    body += _box(
        830,
        110,
        170,
        120,
        "casebook check",
        ["nine checks per", "household, each", "pass or fail"],
        fill="#e8f1f8",
        stroke=ACCENT,
        title_fill=ACCENT,
    )
    body += _box(830, 254, 170, 136, "Gates", ["the notice", "aliases only", "no private set", "watermarked forms"])
    body += _arrow(915, 230, 915, 254)
    body.append(_text(830, 418, "A fail stops here:", size=12, fill=STOP, weight="bold"))
    body.append(_text(830, 436, "nothing is published", size=12, fill=STOP))
    # What comes out.
    outputs = (
        ("Site", "out/site/"),
        ("Plugin sample book", "plugin/book/"),
        ("Release bundle", "out/release/v0.1.0/"),
    )
    for i, (name, where) in enumerate(outputs):
        y = 110 + i * 100
        body += _box(1044, y, 196, 76, name, [where])
        body.append(_elbow([(1000, 322), (1022, 322), (1022, y + 38), (1044, y + 38)]))
    return _svg(
        1272,
        470,
        "How a book is made and checked",
        f"Seed 2026 and the committed scripts build {households} households in ten archetypes, each with four "
        "source sets and a sealed layer. casebook check runs nine checks per household; the gates check the "
        "notice, aliases, the private set and watermarks; only then are the site, the plugin's sample book and "
        "the release written.",
        body,
    )


def run_diagram(held: int, public: int) -> str:
    """How a task is run and graded: three arms on one sealed workspace, the answer, the independent key, the grade."""
    body: list[str] = [
        _text(32, 44, "How a task is run and graded", size=22, weight="bold"),
        _text(
            32,
            70,
            "One run is one task under one arm. The three arms share one configuration: only the instruction differs.",
        ),
    ]
    body += _box(32, 110, 196, 128, "Task file", ["prompt, fixtures,", "cutoff date,", "allowed tools"])
    body += _box(32, 262, 196, 92, "Real-ticker build", ["out/real/: real tickers,", "invented prices"])
    body += _arrow(228, 174, 268, 174)
    body += [_elbow([(228, 308), (248, 308), (248, 190), (268, 190)])]
    body += _box(
        268,
        110,
        250,
        244,
        "Sealed workspace",
        [
            "Only this household's files,",
            "each known by the cutoff",
            "",
            "No event log, registry or",
            "answer key reachable:",
            "the run refuses to start",
            "",
            "Held-out pairs refused",
            "unless the freeze matches",
        ],
        fill="#e8f1f8",
        stroke=ACCENT,
        title_fill=ACCENT,
    )
    arms = (("Basic prompt", "the task alone"), ("Checklist", "the generic checklist"), ("Skill", "the advisor skill"))
    body.append(_text(562, 102, "Three arms, same model, tools, limits", size=13, fill=MUTED, weight="bold"))
    for i, (name, what) in enumerate(arms):
        y = 110 + i * 84
        body.append(f'<rect x="562" y="{y}" width="230" height="72" rx="8" fill="{PANEL}" stroke="{LINE}"/>')
        body.append(_text(576, y + 28, name, size=15, weight="bold"))
        body.append(_text(576, y + 50, what, size=13, fill=MUTED))
        body += _arrow(518, 232, 562, y + 36)
        body += _arrow(792, y + 36, 836, 232)
    body += _box(836, 172, 170, 120, "Answer", ["fenced JSON:", "the finding, every", "figure and its file"])
    body += _box(
        836,
        320,
        170,
        100,
        "Answer key",
        ["computed by code", "that never imports", "the generator"],
        fill=PAPER,
        dashed=True,
    )
    body += _box(1050, 172, 190, 120, "Grader", ["score out of 100,", "three counts,", "critical fails zero it"])
    body += _arrow(1006, 232, 1050, 232)
    body += [_elbow([(1006, 370), (1080, 370), (1080, 292)])]
    # Where the grade goes.
    body += _box(
        562,
        488,
        444,
        100,
        "Published",
        ["The run record, mapped back to aliases, in published/runs/.", "The task page and the results page show it."],
    )
    body += _box(
        1050,
        488,
        190,
        100,
        "Held",
        [f"{held} of {public} tasks: tax-lot,", "RMD or a tax figure.", "No verdict until review."],
        fill=NOTICE_BG,
        stroke=NOTICE_LINE,
    )
    body += [_elbow([(1200, 292), (1200, 488)])]
    body += [_elbow([(1160, 292), (1160, 455), (784, 455), (784, 488)])]
    return _svg(
        1272,
        620,
        "How a task is run and graded",
        "A task file and the real-ticker build give a sealed workspace that holds only the household's files known "
        "by the cutoff. The basic prompt, checklist and skill arms run on it under one configuration. Each answer is "
        f"graded against an answer key computed by independent code. The run record is published under aliases; "
        f"{held} of the {public} public tasks are held, with no verdict until the tax review.",
        body,
    )


# ---------------------------------------------------------------- the results chart

UNIT = 12  # pixels per run
BAR = 12
ROW = 24


def _counts_words(counts: dict[str, int]) -> str:
    words = [f"{counts[kind]} {OUTCOME_NAMES[kind]}" for kind in OUTCOMES if counts[kind]]
    return " · ".join(words) if words else "no runs"


def _bar(x: float, y: float, counts: dict[str, int]) -> list[str]:
    parts: list[str] = []
    for kind in OUTCOMES:
        if counts[kind]:
            width = counts[kind] * UNIT - 2  # a 2px gap of the surface between segments
            parts.append(
                f'<rect x="{x:g}" y="{y:g}" width="{width:g}" height="{BAR}" rx="2" fill="{OUTCOME_FILL[kind]}"/>'
            )
            x += counts[kind] * UNIT
    parts.append(_text(x + 8, y + 10.5, _counts_words(counts), size=13, fill=INK))
    return parts


def _ran(section: RunSetResult, workflow: str) -> bool:
    """Whether any run under this name, public or private, falls in the workflow."""
    sets = [section.public, *([section.private] if section.private else [])]
    return any(counts[workflow][arm][kind] for counts in sets for arm in ARM_ORDER for kind in OUTCOMES)


def results_chart(sections: Sequence[RunSetResult], held: int, public: int) -> str:
    left, pub_x, priv_x, width = 32, 280, 830, 1272
    body: list[str] = [
        _text(left, 44, "Committed results: runs by workflow and arm", size=22, weight="bold"),
        _text(
            left,
            70,
            "Counted as the results page counts them, from published/runs and published/results/private-outcomes.json.",
            fill=MUTED,
        ),
        _text(
            left,
            90,
            "Each workflow is counted on its own: there is no combined score. Runs under two names are never pooled.",
            fill=MUTED,
        ),
    ]
    legend = (
        ("passed", "passed"),
        ("failed", "failed"),
        ("failed_run", "failed run (never scored)"),
        ("held", "held: no verdict until the tax review"),
    )
    x = left
    for kind, words in legend:
        body.append(f'<rect x="{x}" y="110" width="14" height="14" rx="2" fill="{OUTCOME_FILL[kind]}"/>')
        body.append(_text(x + 20, 122, words, size=13))
        x += 20 + len(words) * 7 + 28
    y = 160
    for section in sections:
        name = section.name
        body.append(f'<line x1="{left}" y1="{y - 18}" x2="{width - left}" y2="{y - 18}" stroke="{LINE}"/>')
        body.append(
            _text(left, y + 4, f"{name.tool} {name.version} · model {', '.join(name.models)}", size=16, weight="bold")
        )
        effort = f"{name.effort} effort · " if name.effort else ""
        body.append(_text(left, y + 26, f"{effort}{name.freeze_label} · {section.dates}", fill=MUTED))
        y += 56
        body.append(_text(pub_x, y, "Public tasks", weight="bold", fill=MUTED))
        body.append(_text(priv_x, y, "Private set (counts only)", weight="bold", fill=MUTED))
        y += 22
        shown = [w for w in WORKFLOWS if _ran(section, w)]
        for workflow in shown:
            body.append(_text(left, y + 10, WORKFLOW_NAMES[workflow], size=14, weight="bold"))
            y += ROW
            for arm in ARM_ORDER:
                body.append(_text(left + 16, y + 10.5, ARM_NAMES[arm], fill=MUTED))
                body += _bar(pub_x, y, section.public[workflow][arm])
                if section.private is None:
                    body.append(_text(priv_x, y + 10.5, "no private runs", fill=MUTED))
                else:
                    body += _bar(priv_x, y, section.private[workflow][arm])
                y += ROW
            y += 8
        left_out = [WORKFLOW_NAMES[w] for w in WORKFLOWS if w not in shown]
        if left_out:
            body.append(_text(left, y + 10, f"No runs under this name: {', '.join(left_out)}.", fill=MUTED))
            y += ROW
        y += 40
    body.append(_text(left, y - 8, f"{NOTICE_HEADLINE} No performance claims are established.", size=13, weight="bold"))
    body.append(
        _text(
            left,
            y + 12,
            f"Held: {held} of the {public} public tasks (every tax-lot and RMD task, and any whose key computes "
            "a tax figure).",
            fill=MUTED,
        )
    )
    body.append(
        _text(
            left,
            y + 32,
            "Drawn by tools/readme_images.py. The results page has every run by task, arm and repeat.",
            fill=MUTED,
        )
    )
    pattern = (
        '<pattern id="held" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
        '<rect width="6" height="6" fill="#d5dbe0"/>'
        '<line x1="0" y1="0" x2="0" y2="6" stroke="#8b96a0" stroke-width="2"/>'
        "</pattern>"
    )
    return _svg(
        width,
        int(y + 56),
        "Committed results by workflow and arm",
        "For each named run set (tool, version, model, freeze and dates), the number of runs per workflow and arm "
        "that passed, failed, failed to run or are held, public tasks beside the private set's counts. "
        "No combined score.",
        body,
        defs=pattern,
    )


def committed_results(runs: Path, tasks: Path) -> list[RunSetResult]:
    private = load_private_outcomes(private_outcomes_path(runs))
    return results(load_records(runs), tasks, private)


# ---------------------------------------------------------------- main


def draw(book: Path, site: Path, out: Path) -> list[Path]:
    """Every image, from a default book and the site built from it and the committed runs."""
    runs, tasks = cli.PUBLISHED_RUNS, Path("tasks/public")
    public = sorted(tasks.glob("T-*.toml"))
    held = sum(is_held(load_task(path)) for path in public)
    households = read_json(book, SEALED_HOUSEHOLDS)["households"]
    featured = sum(h["set"] == "featured" for h in households)
    drawn = {
        "book-made-and-checked.svg": book_diagram(len(households), featured),
        "task-run-and-graded.svg": run_diagram(held, len(public)),
        "results-chart.svg": results_chart(committed_results(runs, tasks), held, len(public)),
    }
    written: list[Path] = []
    for name, svg in drawn.items():
        (out / name).write_text(svg, encoding="utf-8")
        written.append(out / name)
    return written + screenshots(site, out)


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=IMAGES)
    parser.add_argument(
        "--built", type=Path, help="a folder holding book/ and site/ as this script builds them: skip the builds"
    )
    args = parser.parse_args(argv)
    built: Path | None = args.built.resolve() if args.built else None
    out: Path = args.out if args.out.is_absolute() else REPO / args.out
    os.chdir(REPO)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="casebook-readme-") as folder:
        root = built or Path(folder)
        book, site = root / "book", root / "site"
        if built is None:
            ok = cli.main(["build", "--seed", SEED, "--out", str(book)]) == 0
            if not ok or cli.main(["site", "--book", str(book), "--out", str(site)]) != 0:
                print("the book or the site did not build; nothing drawn", file=sys.stderr)
                return 1
        written = draw(book, site, out)
    for path in written:
        print(f"{path.relative_to(REPO) if path.is_relative_to(REPO) else path}: {path.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
