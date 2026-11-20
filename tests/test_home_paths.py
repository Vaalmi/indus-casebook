"""No home-folder path in a published file (the owner's choice 5(a),
docs/decisions/2026-11-19-slice16-release-choices.md): a path inside the repo is published relative to it, one
outside it as a placeholder naming its role; no grade and no hash changes, and the run's own folder under
`$CASEBOOK_PRIVATE` keeps what the run used."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from casebook.cli import main
from casebook.graders.registry import grader
from casebook.publish.mapper import path_rewriter, without_home_paths
from casebook.runner.config import REPO, SharedConfig
from casebook.runner.run import RunInputs, private_root, run_task
from casebook.runner.session import finish_run, grading
from casebook.tasks.task import find_task
from tools import rewrite_home_paths
from tools.rewrite_home_paths import main as rewrite_main
from tools.rewrite_home_paths import rewrite_published

from .conftest import ROOT, StandIn
from .test_follow_up_run import follow_up_task
from .test_pass import freeze_record, frozen
from .test_run_session import answer_for

__all__ = ["freeze_record", "frozen"]  # fixtures this module's tests use
TASKS = ROOT / "tasks" / "public"
# The home-folder paths the decision names, as a published file would show them.
HOME_PATH = re.compile(r"/Users/|/home/|/private/var/folders|/var/folders/|/private/tmp|(?<![\w.-])/tmp/")

# A run on another machine, by hand: its repo, its private folder beside it, and its temp folder.
REPO_THERE = Path("/Users/ada/code/indus-casebook")
PRIVATE_THERE = Path("/Users/ada/code/indus-casebook-private")
MAC_TEMP = "/private/var/folders/xy/k2v9q0l1b7c_9m3n4p5r6s7t0000gn/T"


@pytest.mark.parametrize(
    ("given", "published"),
    [
        ("/Users/ada/code/indus-casebook/out/real/0.0.1", "out/real/0.0.1"),
        ("/Users/ada/code/indus-casebook/skills/indus-advisor", "skills/indus-advisor"),
        ("/Users/ada/code/indus-casebook/checklist/indus-checklist", "checklist/indus-checklist"),
        ("/Users/ada/code/indus-casebook", "."),
        (
            "/Users/ada/code/indus-casebook-private/runs/T-MTG-04-skill-20261118T213101Z-a086/crm-1/mcp.json",
            "<private>/runs/T-MTG-04-skill-20261118T213101Z-a086/crm-1/mcp.json",
        ),
        (f"{MAC_TEMP}/casebook-workspace-3lrbv4bs", "<workspace>"),
        (
            f"{MAC_TEMP}/casebook-workspace-3lrbv4bs/households/HH-4821/crm/crm.json",
            "<workspace>/households/HH-4821/crm/crm.json",
        ),
        (
            "/var/folders/xy/k2v9q0l1b7c_9m3n4p5r6s7t0000gn/T/casebook-workspace-q_x2ab9z/custodian/cash.csv",
            "<workspace>/custodian/cash.csv",
        ),
        ("/tmp/casebook-workspace-0uwvrc7y/portfolio/tax_profile.json", "<workspace>/portfolio/tax_profile.json"),
        (
            f"Note: your current working directory is {MAC_TEMP}/casebook-workspace-3lrbv4bs.",
            "Note: your current working directory is <workspace>.",
        ),
        (
            "Full output saved to: /Users/ada/.claude/projects/-private-var-folders-xy-k2v9q0l1b7c-9m3n4p5r6s7t0000gn"
            "-T-casebook-workspace-ktd6ah-2/f33fa025-b379-4e64-b979-ee3d0ada1faa/tool-results/toolu_01.txt",
            "Full output saved to: <home>/.claude/projects/<workspace>/f33fa025-b379-4e64-b979-ee3d0ada1faa"
            "/tool-results/toolu_01.txt",
        ),
        ("/private/tmp/casebook-crm-abc/state.json", "<temp>/casebook-crm-abc/state.json"),
        ("/Users/ada/Downloads/notes.txt", "<home>/Downloads/notes.txt"),
        ("/home/runner/work/x.json", "<home>/work/x.json"),
        # Not a home-folder path: a path relative to the workspace, a folder named tmp inside it, plain text.
        ("custodian/transactions.csv", "custodian/transactions.csv"),
        ("out/tmp/x", "out/tmp/x"),
        ("The fee was right: $1,072.56 on 2025-10-02.", "The fee was right: $1,072.56 on 2025-10-02."),
    ],
)
def test_a_home_folder_path_is_published_relative_to_the_repo_or_as_its_role(given: str, published: str) -> None:
    assert path_rewriter(REPO_THERE, PRIVATE_THERE)(given) == published


def test_every_string_of_a_record_is_rewritten_keys_too_and_nothing_else() -> None:
    record = {
        "dataset": {"book": "/Users/ada/code/indus-casebook/out/real/0.0.1", "real_tickers": True},
        "tools_and_permissions": {"arguments": ["claude", "--plugin-dir", "/Users/ada/code/indus-casebook/skills/x"]},
        "token_use": {"input_tokens": 14},
        "/Users/ada/notes": None,
    }
    assert without_home_paths(record, path_rewriter(REPO_THERE, PRIVATE_THERE)) == {
        "dataset": {"book": "out/real/0.0.1", "real_tickers": True},
        "tools_and_permissions": {"arguments": ["claude", "--plugin-dir", "skills/x"]},
        "token_use": {"input_tokens": 14},
        "<home>/notes": None,
    }


def _published(tmp_path: Path) -> tuple[dict[str, Any], list[str]]:
    [record_file] = (tmp_path / "runs" / "T-REC-01").glob("*[0-9a-f].json")
    [transcript] = (tmp_path / "runs" / "T-REC-01").glob("*.transcript.jsonl")
    return json.loads(record_file.read_text()), transcript.read_text().splitlines()


def test_a_run_is_published_with_no_home_folder_path_and_the_same_grade(
    tmp_path: Path, real_book: Path, standin_cli: StandIn
) -> None:
    standin_cli.answer.write_text(answer_for(real_book))
    paths = ["--keys", str(tmp_path / "keys"), "--runs", str(tmp_path / "runs")]
    assert (
        main(["run", "--task", "T-REC-01", "--arm", "skill", "--book", str(real_book), "--tasks", str(TASKS), *paths])
        == 0
    )
    published, lines = _published(tmp_path)
    args = published["tools_and_permissions"]["arguments"]
    assert args[args.index("--plugin-dir") + 1] == "skills/indus-advisor"
    # The tests' book is built in the temp folder, so its path is published from there.
    assert published["dataset"]["book"].startswith("<temp>/") and published["dataset"]["book"].endswith("/0.0.1")
    init = json.loads(lines[1])
    assert (init["type"], init["cwd"]) == ("system", "<workspace>")
    for path in (tmp_path / "runs").rglob("*"):
        assert not path.is_file() or not HOME_PATH.search(path.read_text()), path

    # The private run folder keeps what the run used, and its grade, hashes and answer are the published ones.
    folder = private_root() / "runs" / published["run_id"]
    private = json.loads((folder / "record.json").read_text())
    kept = private["tools_and_permissions"]["arguments"]
    assert Path(kept[kept.index("--plugin-dir") + 1]) == REPO / "skills" / "indus-advisor"
    assert private["dataset"]["book"] == real_book.as_posix()
    assert (published["hashes"], published["output"], published["grade"]) == (
        private["hashes"],
        private["output"],
        private["grade"],
    )
    # Graded again from each, the rewritten record and the one the run wrote grade alike, as they were graded.
    task = find_task(TASKS, "T-REC-01")
    spec = grader(task.grader)
    key = spec.key(real_book, task.household_id, task.grader_params)
    workspace = folder / "workspace-1"
    again = [grading(task, spec, key, r)(r["output"], workspace) for r in (published, private)]
    assert again == [private["grade"], private["grade"]] and private["grade"]["score"] == 100


def test_a_follow_up_run_s_sandbox_config_is_published_under_the_private_placeholder(
    tmp_path: Path, real_book: Path, standin_cli: StandIn, frozen: Path
) -> None:
    standin_cli.set("error")
    task = follow_up_task()
    inputs = RunInputs(task, "basic", real_book, None, "grader-sha", "key-sha")
    record = run_task(inputs, SharedConfig(timeout_seconds=30, retries=0), private_root())
    assert record["state"] == "failed"
    public = finish_run(task, TASKS, False, grader(task.grader), None, tmp_path / "keys", record, tmp_path / "runs")
    args = public["tools_and_permissions"]["arguments"]
    assert args[args.index("--mcp-config") + 1] == f"<private>/runs/{record['run_id']}/crm-1/mcp.json"
    kept = record["tools_and_permissions"]["arguments"]
    assert Path(kept[kept.index("--mcp-config") + 1]).is_relative_to(private_root())


RECORD = {
    "dataset": {"book": "/Users/ada/code/indus-casebook/out/real/0.0.1", "version": "0.0.1"},
    "grade": {"score": 80},
    "hashes": {"skill": "4" * 64},
    "output": "The fee was right.",
    "tools_and_permissions": {"arguments": ["claude", "--plugin-dir", "/Users/ada/code/indus-casebook/skills/x"]},
}
EVENTS = [
    {"notice": "SYNTHETIC"},
    {"type": "system", "cwd": f"{MAC_TEMP}/casebook-workspace-3lrbv4bs", "plugins": [{"name": "x"}]},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "Reading the files — fees first."}]}},
]


def _published_folder(root: Path, record: dict[str, Any] = RECORD) -> Path:
    runs = root / "published" / "runs" / "T-REC-01"
    runs.mkdir(parents=True)
    (runs / "T-REC-01-skill-x.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    (runs / "T-REC-01-skill-x.transcript.jsonl").write_text("".join(json.dumps(e) + "\n" for e in EVENTS))
    return root / "published"


def test_the_one_off_rewrite_changes_only_the_paths_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rewrite_home_paths, "REPO", REPO_THERE)
    published = _published_folder(tmp_path)
    report = rewrite_published(published, PRIVATE_THERE)
    assert report.lines() == [
        "1 records files rewritten",
        "1 transcripts files rewritten",
        "1 records .dataset.book",
        "1 records .tools_and_permissions.arguments[]",
        "1 transcripts .cwd",
    ]
    runs = published / "runs" / "T-REC-01"
    record = (runs / "T-REC-01-skill-x.json").read_text()
    assert record == (
        "{\n"
        '  "dataset": {\n    "book": "out/real/0.0.1",\n    "version": "0.0.1"\n  },\n'
        '  "grade": {\n    "score": 80\n  },\n'
        f'  "hashes": {{\n    "skill": "{"4" * 64}"\n  }},\n'
        '  "output": "The fee was right.",\n'
        '  "tools_and_permissions": {\n    "arguments": [\n      "claude",\n      "--plugin-dir",\n'
        '      "skills/x"\n    ]\n  }\n'
        "}\n"
    )
    assert (runs / "T-REC-01-skill-x.transcript.jsonl").read_text().splitlines() == [
        '{"notice": "SYNTHETIC"}',
        '{"type": "system", "cwd": "<workspace>", "plugins": [{"name": "x"}]}',
        '{"type": "assistant", "message": {"content": [{"type": "text", "text": '
        '"Reading the files \\u2014 fees first."}]}}',
    ]
    # Run again, it finds nothing to do.
    assert rewrite_published(published, PRIVATE_THERE).lines() == []


def test_the_one_off_rewrite_refuses_to_touch_a_grade_or_an_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(rewrite_home_paths, "REPO", REPO_THERE)
    published = _published_folder(tmp_path, {**RECORD, "output": "I read /Users/ada/code/indus-casebook/README.md."})
    before = {p: p.read_bytes() for p in published.rglob("*") if p.is_file()}
    assert rewrite_main(["--published", str(published), "--private", str(PRIVATE_THERE)]) == 1
    assert "the rewrite would change output" in capsys.readouterr().err
    assert {p: p.read_bytes() for p in published.rglob("*") if p.is_file()} == before


def test_no_committed_published_file_holds_a_home_folder_path() -> None:
    private_name = re.compile(r"indus-casebook-private")
    for path in sorted(p for p in (ROOT / "published").rglob("*") if p.is_file()):
        text = path.read_text(encoding="utf-8")
        assert not HOME_PATH.search(text) and not private_name.search(text), path.relative_to(ROOT)
