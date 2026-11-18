"""docs/PLAN.md, slice 13: the results page shows paired outcomes per task, counts per workflow, consistency across
repeats, public and private outcomes side by side for each arm, and the tool, version, model and date; no combined
score, and every held task's outcome as held. Built here from hand-made run records whose outcomes are worked by
hand below."""

import itertools
import json
import re
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser

from casebook.model.files import json_text
from casebook.notice import NOTICE
from casebook.publish.site_build import build_site
from casebook.site.results import RESULTS_DIR, RunSetResult, TaskResult
from casebook.site.results import results as result_sections
from casebook.site.tasks import ARM_ORDER
from casebook.tasks.task import WORKFLOWS

from .conftest import README, ROOT
from .test_site_browser import visit

TASKS = ROOT / "tasks" / "public"
# Slice 2's skill run, by name: the full pass adds runs beside it.
BASE = json.loads((ROOT / "published" / "runs" / "T-REC-01" / "T-REC-01-skill-20261116T135933Z-4321.json").read_text())
FREEZE = "f" * 64
OPUS = "claude-opus-5-5"
FABLE = "claude-fable-5-1"
_serial = itertools.count(1)


def record(task_id: str, arm: str, started: str, result: str, model: str = OPUS, **extra: Any) -> dict[str, Any]:
    """A published run record: `result` is "passed 100", "failed 40", "run quota" (a failed run and its reason)
    or "held" (a held task's mapped record, with no grade)."""
    kind, _, value = result.partition(" ")
    run_id = f"{task_id}-{arm}-{started.replace('-', '').replace(':', '')[:15]}Z-{next(_serial):04x}"
    rec = BASE | {
        "task_id": task_id,
        "arm": arm,
        "run_id": run_id,
        "started_utc": f"{started}:00+00:00",
        "ended_utc": f"{started}:59+00:00",
        "models_reported": [model],
        "model_requested": model,
        "cli_version": "2.1.304 (Claude Code)",
        "freeze": FREEZE,
        "state": "mapped",
        "failure_reason": None,
        "verdict_held": None,
        **extra,
    }
    if kind == "run":
        return rec | {"state": "failed", "failure_reason": value, "grade": None, "output": None}
    if kind == "held":
        return rec | {"grade": None, "verdict_held": True}
    grade: dict[str, Any] = {"passed": kind == "passed", "score": int(value), "breakdown": []}
    grade |= {"critical_fail": None, "counts": {"correct_unresolved": 0, "unnecessary_refusal": 0, "false_alarm": 0}}
    return rec | {"grade": grade}


# Each task's outcomes by arm, repeat 1 to 3, started in that order on 18 November 2026.
OUTCOMES = {
    "T-REC-01": {
        "basic": ["failed 40", "failed 40", "passed 100"],
        "checklist": ["passed 90", "failed 60", "passed 100"],
        "skill": ["passed 100", "passed 100", "passed 100"],
    },
    "T-REC-02": {
        "basic": ["passed 100", "passed 100", "passed 100"],
        "checklist": ["passed 100", "run quota", "passed 100"],
        "skill": ["failed 70", "passed 100", "passed 100"],
    },
    "T-REC-05": {
        "basic": ["failed 30", "failed 30", "failed 30"],
        "checklist": ["failed 30", "passed 90", "run timeout"],
        # Repeat 1 failed on a timeout and was retried after repeat 3: the retry stands for repeat 1.
        "skill": ["run timeout", "passed 100", "failed 50"],
    },
    "T-TAX-01": {
        "basic": ["held", "run quota", "held"],
        "checklist": ["held", "held", "held"],
        "skill": ["held", "held", "held"],
    },
}


def published_runs(folder: Path) -> Path:
    runs = folder / "runs"
    records: list[dict[str, Any]] = []
    for t, (task_id, arms) in enumerate(OUTCOMES.items()):
        for repeat in range(3):
            for a, (arm, results) in enumerate(arms.items()):
                records.append(record(task_id, arm, f"2026-11-18T{10 + repeat:02d}:{t * 10 + a:02d}", results[repeat]))
    timed_out = next(r for r in records if r["task_id"] == "T-REC-05" and r["arm"] == "skill")
    retry = record("T-REC-05", "skill", "2026-11-18T15:00", "passed 100")
    records.append(retry | {"retries": [{"run_id": timed_out["run_id"], "failure_reason": "timeout"}]})
    # A later run under another model: shown apart, never pooled with the runs above.
    records.append(record("T-REC-01", "basic", "2026-11-19T09:00", "passed 100", model=FABLE))
    for rec in records:
        (runs / rec["task_id"]).mkdir(parents=True, exist_ok=True)
        (runs / rec["task_id"] / f"{rec['run_id']}.json").write_text(json.dumps(rec))
    return runs


def counts(passed: int = 0, failed: int = 0, failed_run: int = 0, held: int = 0) -> dict[str, int]:
    return {"passed": passed, "failed": failed, "failed_run": failed_run, "held": held}


ZERO = {arm: counts() for arm in ARM_ORDER}


def no_counts() -> dict[str, dict[str, dict[str, int]]]:
    """Every workflow's and arm's counts, at zero."""
    return {w: {a: counts() for a in ARM_ORDER} for w in WORKFLOWS}


# Two private workflows' counts, under the same name as the public runs.
PRIVATE_COUNTS = {
    "reconciliation": {"basic": counts(1, 4, 1), "checklist": counts(3, 3), "skill": counts(5, 1)},
    "meeting": ZERO,
    "tax_lot_rmd": ZERO,
    "compliance": {"basic": counts(2, 4), "checklist": counts(4, 1, 1), "skill": counts(6)},
}


def private_summary(published: Path) -> None:
    summary = {
        "notice": NOTICE,
        "run_sets": [
            {
                "tool": "Claude Code",
                "version": "2.1.304",
                "models": [OPUS],
                "effort": "high",
                "freeze": FREEZE,
                "first_date": "2026-11-18",
                "last_date": "2026-11-20",
                "counts": PRIVATE_COUNTS,
            }
        ],
    }
    (published / RESULTS_DIR).mkdir(parents=True)
    (published / RESULTS_DIR / "private-outcomes.json").write_text(json_text(summary))


@pytest.fixture(scope="module")
def site(book: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    published = tmp_path_factory.mktemp("published")
    runs = published_runs(published)
    private_summary(published)
    out = published.parent / "site"
    build_site(book, out, README, runs, TASKS, None)
    return out


@pytest.fixture(scope="module")
def page(site: Path) -> str:
    return (site / "results.html").read_text()


def section(page: str, index: int) -> str:
    return page.split("data-run-set")[index]


def task_block(page: str, task_id: str) -> str:
    start = page.index(f'data-task="{task_id}"')
    return page[start : page.index("</article>", start)]


def row(block: str, attribute: str) -> list[str]:
    start = block.index(attribute)
    cells = block[start : block.index("</tr>", start)]
    return [" ".join(c.split()) for c in re.findall(r"<td[^>]*>(.*?)</td>", cells, re.S)]


def test_the_index_links_the_results_page(site: Path) -> None:
    assert 'href="results.html"' in (site / "index.html").read_text()


def test_each_run_set_is_named_by_tool_version_model_effort_freeze_and_dates(page: str) -> None:
    names = [" ".join(n.split()) for n in re.findall(r"data-run-name>(.*?)</h2>", page, re.S)]
    assert names == [
        "Claude Code 2.1.304 · model claude-opus-5-5 at high effort · freeze ffffffffffff · 2026-11-18 to 2026-11-20",
        "Claude Code 2.1.304 · model claude-fable-5-1 at high effort · freeze ffffffffffff · 2026-11-19",
    ]


def test_each_repeat_s_outcome_shows_under_each_arm(page: str) -> None:
    opus = section(page, 1)
    trap = task_block(opus, "T-REC-01")
    assert row(trap, 'data-arm="basic"')[:3] == ["failed, 40", "failed, 40", "passed, 100"]
    twin = task_block(opus, "T-REC-02")
    assert row(twin, 'data-arm="checklist"')[:3] == ["passed, 100", "failed run: quota", "passed, 100"]
    # The retry stands for the repeat whose run failed, in that repeat's place.
    book = task_block(opus, "T-REC-05")
    assert row(book, 'data-arm="skill"')[:3] == ["passed, 100", "passed, 100", "failed, 50"]


def test_the_skill_is_paired_with_each_other_arm_on_the_same_task_and_repeat(page: str) -> None:
    opus = section(page, 1)
    trap, twin, book = (task_block(opus, t) for t in ("T-REC-01", "T-REC-02", "T-REC-05"))
    assert row(trap, 'data-compare="skill-checklist"')[:3] == ["same", "better", "same"]
    assert row(trap, 'data-compare="skill-basic"')[:3] == ["better", "better", "same"]
    assert row(twin, 'data-compare="skill-checklist"')[:3] == ["worse", "not compared: a failed run", "same"]
    assert row(twin, 'data-compare="skill-basic"')[:3] == ["worse", "same", "same"]
    assert row(book, 'data-compare="skill-checklist"')[:3] == ["better", "same", "not compared: a failed run"]
    assert row(book, 'data-compare="skill-basic"')[:3] == ["better", "better", "same"]


def test_each_trap_task_sits_beside_its_twin_task_and_a_book_level_task_alone(page: str) -> None:
    groups = section(page, 1).split("data-group")[1:]
    tasks = [re.findall(r'data-task="([^"]+)" data-role="([^"]+)"', g) for g in groups]
    assert tasks == [
        [("T-REC-01", "trap"), ("T-REC-02", "twin")],
        [("T-REC-05", "book")],
        [("T-TAX-01", "trap")],
    ]


def test_consistency_across_repeats(page: str) -> None:
    opus = section(page, 1)
    agreement = {
        (t, arm): row(task_block(opus, t), f'data-arm="{arm}"')[-1]
        for t in ("T-REC-01", "T-REC-05")
        for arm in ("basic", "checklist", "skill")
    }
    assert agreement == {
        ("T-REC-01", "basic"): "2 of 3 agree: failed",
        ("T-REC-01", "checklist"): "2 of 3 agree: passed",
        ("T-REC-01", "skill"): "3 of 3 agree: passed",
        ("T-REC-05", "basic"): "3 of 3 agree: failed",
        ("T-REC-05", "checklist"): "no two of 3 agree",
        ("T-REC-05", "skill"): "2 of 3 agree: passed",
    }


def cell(page: str, workflow: str, arm: str, which: str) -> str:
    start = page.index(f'data-workflow="{workflow}"')
    tr = page[start : page.index("</tr>", start)]
    found = re.search(rf'data-arm="{arm}" data-set="{which}">(.*?)</td>', tr, re.S)
    assert found is not None
    return " ".join(re.sub(r"<[^>]+>", "", found.group(1)).split())


def test_counts_per_workflow_public_beside_private_for_each_arm(page: str) -> None:
    opus = section(page, 1)
    # Reconciliation, by hand from the outcomes above (the retried timeout is not counted; its retry is).
    assert cell(opus, "reconciliation", "basic", "public") == "passed 4 · failed 5 · failed run 0 · held 0"
    assert cell(opus, "reconciliation", "checklist", "public") == "passed 5 · failed 2 · failed run 2 · held 0"
    assert cell(opus, "reconciliation", "skill", "public") == "passed 7 · failed 2 · failed run 0 · held 0"
    assert cell(opus, "reconciliation", "basic", "private") == "passed 1 · failed 4 · failed run 1 · held 0"
    assert cell(opus, "compliance", "checklist", "private") == "passed 4 · failed 1 · failed run 1 · held 0"
    # The held task's runs are held, its failed run among them.
    assert cell(opus, "tax_lot_rmd", "basic", "public") == "passed 0 · failed 0 · failed run 0 · held 3"
    assert cell(opus, "meeting", "skill", "public") == "passed 0 · failed 0 · failed run 0 · held 0"
    fable = section(page, 2)
    assert cell(fable, "reconciliation", "basic", "public") == "passed 1 · failed 0 · failed run 0 · held 0"
    assert cell(fable, "reconciliation", "basic", "private") == "no private runs"


def test_two_models_runs_are_never_pooled(page: str) -> None:
    opus, fable = section(page, 1), section(page, 2)
    assert row(task_block(opus, "T-REC-01"), 'data-arm="basic"') == [
        "failed, 40",
        "failed, 40",
        "passed, 100",
        "2 of 3 agree: failed",
    ]
    assert row(task_block(fable, "T-REC-01"), 'data-arm="basic"') == ["passed, 100", "1 run: passed"]
    assert re.findall(r'data-task="([^"]+)"', fable) == ["T-REC-01"]


def test_a_held_task_shows_no_verdict(page: str) -> None:
    held = task_block(section(page, 1), "T-TAX-01")
    assert set(re.findall(r'data-outcome="([^"]+)"', held)) == {"held"}
    assert set(re.findall(r'data-verdict="([^"]+)"', held)) == {"held"}
    text = re.sub(r"<[^>]+>", " ", held)
    for verdict in ("passed", "failed", "better", "worse", "same", "quota", "100"):
        assert verdict not in text, verdict


def test_no_combined_score(page: str) -> None:
    text = " ".join(re.sub(r"<[^>]+>", " ", page).split()).lower()
    for word in ("total", "average", "overall", "mean", "%", "all workflows"):
        assert word not in text, word
    # Four workflow rows in each counts table, and no row beyond them.
    for index in (1, 2):
        table = section(page, index).split('data-section="counts"')[1].split("</table>")[0]
        assert table.count("<tr data-workflow=") == 4 and table.count("<tr") == 2 + 4


def test_the_results_page_in_the_browser_at_phone_and_desktop_widths(site: Path, browser: Browser) -> None:
    for width in (390, 1440):
        tab, noise = visit(browser, (site / "results.html").as_uri(), width)
        assert tab.locator("[data-run-set]").count() == 2
        assert tab.evaluate("document.documentElement.scrollWidth") <= width
        trap = tab.locator("[data-run-set]").first.locator('[data-task="T-REC-01"]')
        twin = tab.locator("[data-run-set]").first.locator('[data-task="T-REC-02"]')
        trap_box, twin_box = trap.bounding_box(), twin.bounding_box()
        assert trap_box is not None and twin_box is not None
        if width == 1440:  # side by side; stacked on a phone
            assert abs(trap_box["y"] - twin_box["y"]) < 1
        tab.close()
        assert noise == []


# Repeats by identity (reviewers A and B, slice 13 round 1).

PASS = "pass-20261118T100000Z-0001"
OLD, NEW = "2.1.304 (Claude Code)", "2.1.305 (Claude Code)"


def slotted(task_id: str, arm: str, started: str, result: str, repeat: int, cli: str, **extra: Any) -> dict[str, Any]:
    """A pass's run record, naming its slot."""
    slot = {"pass_id": PASS, "repeat": repeat}
    return record(task_id, arm, started, result, cli_version=cli, slot=slot, **extra)


def task_in(sections: list[RunSetResult], version: str, task_id: str) -> TaskResult:
    [section] = [s for s in sections if s.name.version == version]
    return next(t for w in section.workflows for g in w.groups for t in g if t.task.task_id == task_id)


def by_arm(result: TaskResult) -> dict[str, list[str]]:
    rows = {a.arm: [o.text if o else "not run" for o in a.outcomes] for a in result.arms}
    return rows | {f"{c.arm}-{c.against}": list(c.verdicts) for c in result.comparisons}


def test_a_pass_s_runs_sit_in_their_repeat_s_column_when_the_cli_s_version_changes_between_arms() -> None:
    """Reviewers A and B, slice 13 round 1: once runs were split by name, each arm's runs were numbered 1, 2, 3 in
    the order they stood, so an arm whose repeat 1 ran under another CLI version had its repeat 2 compared with the
    other arm's repeat 1. Each run is now placed by its slot's repeat, a gap where that repeat's run is under the
    other version, and only the same repeat's outcomes are compared."""
    trap: list[dict[str, Any]] = [
        # Reviewer B's trigger: the CLI is upgraded between the checklist's and the skill's repeat 1.
        slotted("T-REC-01", "basic", "2026-11-18T10:00", "passed 100", 1, OLD),
        slotted("T-REC-01", "checklist", "2026-11-18T10:01", "passed 100", 1, OLD),
        slotted("T-REC-01", "skill", "2026-11-18T10:02", "passed 100", 1, NEW),
        slotted("T-REC-01", "basic", "2026-11-18T11:00", "failed 40", 2, NEW),
        slotted("T-REC-01", "checklist", "2026-11-18T11:01", "failed 40", 2, NEW),
        slotted("T-REC-01", "skill", "2026-11-18T11:02", "failed 40", 2, NEW),
        slotted("T-REC-01", "basic", "2026-11-18T12:00", "passed 100", 3, NEW),
        slotted("T-REC-01", "checklist", "2026-11-18T12:01", "passed 100", 3, NEW),
        slotted("T-REC-01", "skill", "2026-11-18T12:02", "passed 100", 3, NEW),
    ]
    # Reviewer A's trigger: the skill's repeat 1 fails, repeats 2 and 3 finish, and repeat 1's retry runs after an
    # upgrade.
    quota = slotted("T-REC-02", "skill", "2026-11-18T10:12", "run quota", 1, OLD)
    twin: list[dict[str, Any]] = [
        slotted("T-REC-02", "basic", "2026-11-18T10:10", "passed 100", 1, OLD),
        slotted("T-REC-02", "checklist", "2026-11-18T10:11", "failed 60", 1, OLD),
        quota,
        *(
            slotted("T-REC-02", arm, f"2026-11-18T{10 + r}:1{a}", "passed 100", r, OLD)
            for r in (2, 3)
            for a, arm in enumerate(ARM_ORDER)
        ),
        slotted(
            "T-REC-02",
            "skill",
            "2026-11-18T15:00",
            "passed 100",
            1,
            NEW,
            retries=[{"run_id": quota["run_id"], "failure_reason": "quota"}],
        ),
    ]
    sections = result_sections({"T-REC-01": trap, "T-REC-02": twin}, TASKS)
    assert [s.columns for s in sections] == [("Repeat 1", "Repeat 2", "Repeat 3")] * 2
    assert by_arm(task_in(sections, "2.1.305", "T-REC-01")) == {
        "basic": ["not run", "failed, 40", "passed, 100"],
        "checklist": ["not run", "failed, 40", "passed, 100"],
        "skill": ["passed, 100", "failed, 40", "passed, 100"],
        "skill-checklist": ["not run", "same", "same"],
        "skill-basic": ["not run", "same", "same"],
    }
    assert by_arm(task_in(sections, "2.1.304", "T-REC-01")) == {
        "basic": ["passed, 100", "not run", "not run"],
        "checklist": ["passed, 100", "not run", "not run"],
        "skill": ["not run"] * 3,
        "skill-checklist": ["not run"] * 3,
        "skill-basic": ["not run"] * 3,
    }
    assert by_arm(task_in(sections, "2.1.304", "T-REC-02")) == {
        "basic": ["passed, 100"] * 3,
        "checklist": ["failed, 60", "passed, 100", "passed, 100"],
        "skill": ["not run", "passed, 100", "passed, 100"],
        "skill-checklist": ["not run", "same", "same"],
        "skill-basic": ["not run", "same", "same"],
    }
    assert by_arm(task_in(sections, "2.1.305", "T-REC-02"))["skill"] == ["passed, 100", "not run", "not run"]
