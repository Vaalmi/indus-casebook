"""The plugin's household gate, `plugin/hooks/gate.py`, hook by hook (docs/SPEC.md, Rules: "the runner and the plugin
accept only household IDs listed in the book manifest. Nothing in the product reads a file from outside the book";
the owner's decision of 19 November 2026, docs/decisions/2026-11-19-plugin-gate.md)."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from casebook.notice import NOTICE

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "plugin" / "hooks" / "gate.py"
SESSION = "session-1"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("plugin_gate", GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load()


@pytest.fixture(autouse=True)
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "plugin-data"
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(folder))
    return folder


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    """A sample book of two households, laid out as `casebook sample-book` writes one."""
    root = tmp_path / "plugin" / "book"
    for household in ("HH-1204", "HH-5271"):
        (root / "households" / household / "custodian").mkdir(parents=True)
        (root / "households" / household / "custodian" / "positions.csv").write_text("security_id,units\n")
    (root / "securities").mkdir()
    (root / "securities" / "securities.csv").write_text("security_id,security\n")
    manifest = {"households": [{"household_id": "HH-1204"}, {"household_id": "HH-5271"}], "files": {}}
    (root / "manifest.json").write_text(json.dumps(manifest))
    (root / "metadata.json").write_text(json.dumps({"scenario_date": "2026-04-15", "notice": NOTICE}))
    (root / "NOTICE.txt").write_text(NOTICE + "\n")
    return root


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    """An advisor's own file, beside the plugin."""
    folder = tmp_path / "clients"
    folder.mkdir()
    (folder / "real-client.csv").write_text("account,balance\n")
    return folder / "real-client.csv"


def call(hook: str, data: dict[str, Any], book: Path) -> dict[str, Any] | None:
    handlers = {
        "prompt": gate.on_prompt,
        "expansion": gate.on_expansion,
        "tool": gate.on_tool,
        "skill": gate.on_skill,
        "stop": gate.on_stop,
    }
    return handlers[hook]({"session_id": SESSION, **data}, book)


def tool(name: str, book: Path, cwd: Path | None = None, **fields: Any) -> dict[str, Any] | None:
    return call("tool", {"tool_name": name, "tool_input": fields, "cwd": str(cwd or book)}, book)


def denied(result: dict[str, Any] | None) -> str:
    assert result is not None, "the gate let the call through"
    decision = result["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    return decision["permissionDecisionReason"]


def start(book: Path, skill: str = "indus-casebook:reconciliation-as-of") -> None:
    assert tool("Skill", book, skill=skill) is None
    assert gate.is_gated(SESSION)


# ---- outside a session that uses the plugin, the gate stays out of the way -------------------------------------


@pytest.mark.parametrize(
    ("name", "fields"),
    [
        ("Bash", {"command": "cat ~/.ssh/id_rsa"}),
        ("Read", {"file_path": "/etc/hosts"}),
        ("WebFetch", {"url": "https://example.com"}),
        ("Write", {"file_path": "/tmp/x", "content": ""}),
        ("Skill", {"skill": "commit"}),
        ("Skill", {"skill": "other-plugin:reconciliation-as-of"}),
    ],
)
def test_an_ungated_session_is_left_alone(sample: Path, name: str, fields: dict[str, Any]) -> None:
    assert tool(name, sample, cwd=Path("/"), **fields) is None
    assert not gate.is_gated(SESSION)


def test_an_ungated_session_s_prompts_and_answers_are_left_alone(sample: Path) -> None:
    assert call("prompt", {"prompt": "summarise HH-0001 from @/etc/hosts", "cwd": "/"}, sample) is None
    assert call("stop", {"last_assistant_message": "Done.", "stop_hook_active": False}, sample) is None
    assert call("skill", {"tool_name": "Skill", "tool_input": {"skill": "commit"}}, sample) is None


# ---- a plugin skill gates the session --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "skill",
    [
        "indus-casebook:reconciliation-as-of",
        "indus-casebook:tax-lot-rmd",
        "indus-casebook:meeting-follow-up",
        "indus-casebook:compliance-review",
        "compliance-review",
    ],
)
def test_each_plugin_skill_gates_its_session(sample: Path, outside: Path, skill: str) -> None:
    start(sample, skill)
    assert "not in the sample book" in denied(tool("Read", sample, file_path=str(outside)))


def test_a_skill_s_context_names_the_sample_book_its_households_and_the_notice(sample: Path) -> None:
    out = call("skill", {"tool_name": "Skill", "tool_input": {"skill": "indus-casebook:tax-lot-rmd"}}, sample)
    assert out is not None
    context = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert str(sample) in context
    assert "HH-1204, HH-5271" in context
    assert NOTICE in context
    assert "2026-04-15" in context


@pytest.mark.parametrize(
    "prompt", ["/indus-casebook:reconciliation-as-of HH-5271", "  /tax-lot-rmd", "/meeting-follow-up\nHH-1204"]
)
def test_a_skill_typed_as_a_command_gates_the_session_and_names_the_book(sample: Path, prompt: str) -> None:
    out = call("prompt", {"prompt": prompt, "cwd": "/"}, sample)
    assert out is not None
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "HH-1204, HH-5271" in out["hookSpecificOutput"]["additionalContext"]
    assert gate.is_gated(SESSION)


@pytest.mark.parametrize(
    "prompt",
    [
        "/summarize /indus-casebook:tax-lot-rmd HH-5271",
        "/noop\n/compliance-review HH-1204",
        "/a /b:c\t/indus-casebook:meeting-follow-up",
    ],
)
def test_a_skill_stacked_after_another_command_gates_the_session(sample: Path, prompt: str) -> None:
    """Reviewers A and B, slice 15 round 1: Claude Code expands several skills typed in one message, so a plugin
    skill typed second gates the session as surely as one typed first."""
    out = call("prompt", {"prompt": prompt, "cwd": "/"}, sample)
    assert out is not None and "HH-1204, HH-5271" in out["hookSpecificOutput"]["additionalContext"]
    assert gate.is_gated(SESSION)


def test_a_stacked_skill_with_an_outside_file_or_household_is_refused(sample: Path, outside: Path) -> None:
    """The reviewers' probe: the prompt is blocked, the session gated, and what follows refused."""
    prompt = f"/summarize /indus-casebook:tax-lot-rmd HH-5271 @{outside}"
    out = call("prompt", {"prompt": prompt, "cwd": "/"}, sample)
    assert out is not None and out["decision"] == "block" and "loads no file of yours" in out["reason"]
    assert gate.is_gated(SESSION)
    assert denied(tool("Read", sample, file_path=str(outside)))
    assert denied(tool("Bash", sample, command=f"cat {outside}"))
    sent_back = call("stop", {"last_assistant_message": "No discrepancy.", "stop_hook_active": False}, sample)
    assert sent_back is not None and sent_back["decision"] == "block"
    other = call("prompt", {"prompt": "/noop /indus-casebook:tax-lot-rmd HH-0001", "cwd": "/"}, sample)
    assert other is not None and other["reason"].startswith("HH-0001 is not in the sample book")


@pytest.mark.parametrize("name", ["indus-casebook:tax-lot-rmd", "reconciliation-as-of"])
def test_a_skill_s_expansion_gates_the_session_once(sample: Path, name: str) -> None:
    out = call("expansion", {"command_name": name, "command_args": "HH-5271"}, sample)
    assert out is not None and out["hookSpecificOutput"]["hookEventName"] == "UserPromptExpansion"
    assert NOTICE in out["hookSpecificOutput"]["additionalContext"]
    assert gate.is_gated(SESSION)
    assert call("expansion", {"command_name": name}, sample) is None


@pytest.mark.parametrize("name", ["commit", "other-plugin:tax-lot-rmd", ""])
def test_another_command_s_expansion_does_not_gate(sample: Path, name: str) -> None:
    assert call("expansion", {"command_name": name}, sample) is None
    assert not gate.is_gated(SESSION)


@pytest.mark.parametrize(
    "prompt",
    [
        "/commit",
        "/other:tax-lot-rmd",
        "use reconciliation-as-of",
        "/tax-lot-rmdx",
        "see @/tmp/tax-lot-rmd",
        "a/tax-lot-rmd",
        # Reviewer A, slice 15 round 2: a skill named in a question, after a command's arguments, or quoted is
        # not invoked by the prompt.
        "What does /indus-casebook:tax-lot-rmd do? Explain without running it.",
        "please run /indus-casebook:meeting-follow-up, then summarise",
        "/commit with args /indus-casebook:tax-lot-rmd",
        "Try `/tax-lot-rmd HH-5271` later",
        # Reviewer A, slice 15's targeted check: the folders of a path are not commands.
        f"/summarize {ROOT / 'plugin' / 'skills' / 'tax-lot-rmd' / 'SKILL.md'}",
        "/summarize/tax-lot-rmd",
        "/tax-lot-rmd/SKILL.md",
    ],
)
def test_other_commands_do_not_gate(sample: Path, prompt: str) -> None:
    assert call("prompt", {"prompt": prompt, "cwd": "/"}, sample) is None
    assert not gate.is_gated(SESSION)


def test_one_session_s_gate_does_not_hold_another(sample: Path, outside: Path) -> None:
    start(sample)
    other = gate.on_tool(
        {"session_id": "session-2", "tool_name": "Read", "tool_input": {"file_path": str(outside)}, "cwd": "/"}, sample
    )
    assert other is None


# ---- in a gated session: reads inside the sample book only ------------------------------------------------------


def test_reads_inside_the_sample_book_go_ahead(sample: Path) -> None:
    start(sample)
    positions = sample / "households" / "HH-5271" / "custodian" / "positions.csv"
    assert tool("Read", sample, file_path=str(positions)) is None
    assert tool("Read", sample, cwd=sample / "households", file_path="HH-5271/custodian/positions.csv") is None
    assert tool("Glob", sample, cwd=Path("/"), path=str(sample), pattern="households/*/custodian/*.csv") is None
    assert tool("Glob", sample, pattern="**/*.csv") is None
    assert tool("Grep", sample, path=str(sample / "households" / "HH-1204"), pattern="units", glob="*.csv") is None
    assert tool("Grep", sample, pattern="units") is None


def test_a_path_outside_the_book_is_refused(sample: Path, outside: Path) -> None:
    """The plan's criterion: "a test passes a path outside the book"."""
    start(sample)
    assert "not in the sample book" in denied(tool("Read", sample, file_path=str(outside)))
    assert "not in the sample book" in denied(tool("Read", sample, file_path="/etc/hosts"))
    assert "not in the sample book" in denied(tool("Read", sample, file_path="../../clients/real-client.csv"))
    assert "not in the sample book" in denied(tool("Read", sample, file_path="~/.ssh/id_rsa"))
    assert "not in the sample book" in denied(tool("Read", sample, file_path=str(sample.parent / "hooks" / "gate.py")))


def test_a_household_the_manifest_does_not_list_is_refused(sample: Path) -> None:
    start(sample)
    stray = sample / "households" / "HH-0001" / "crm"
    stray.mkdir(parents=True)
    (stray / "crm.json").write_text("{}")
    assert "not in the sample book" in denied(tool("Read", sample, file_path=str(stray / "crm.json")))
    assert denied(tool("Glob", sample, path=str(sample / "households" / "HH-0001"), pattern="*"))


def test_a_link_out_of_the_book_is_refused(sample: Path, outside: Path) -> None:
    start(sample)
    link = sample / "households" / "HH-5271" / "custodian" / "linked.csv"
    link.symlink_to(outside)
    folder = sample / "households" / "HH-5271" / "elsewhere"
    folder.symlink_to(outside.parent, target_is_directory=True)
    assert denied(tool("Read", sample, file_path=str(link)))
    assert denied(tool("Read", sample, file_path=str(folder / "real-client.csv")))
    assert denied(tool("Grep", sample, path=str(folder), pattern="balance"))


@pytest.mark.parametrize(
    ("name", "fields", "cwd"),
    [
        ("Glob", {"pattern": "**/*.csv"}, Path("/")),
        ("Glob", {"pattern": "../../clients/*.csv"}, None),
        ("Glob", {"pattern": "/Users/*/clients/*.csv"}, None),
        ("Glob", {"pattern": "~/*.csv"}, None),
        ("Glob", {"path": "/", "pattern": "**/*.csv"}, None),
        ("Grep", {"pattern": "balance"}, Path("/")),
        ("Grep", {"pattern": "balance", "path": "/etc"}, None),
        ("Grep", {"pattern": "balance", "glob": "../**/*.csv"}, None),
    ],
)
def test_a_search_reaching_outside_the_book_is_refused(
    sample: Path, name: str, fields: dict[str, Any], cwd: Path | None
) -> None:
    start(sample)
    assert denied(tool(name, sample, cwd=cwd, **fields))


@pytest.mark.parametrize(
    ("name", "fields"),
    [
        ("Bash", {"command": "ls"}),
        ("Write", {"file_path": "notes.md", "content": "x"}),
        ("Edit", {"file_path": "notes.md", "old_string": "a", "new_string": "b"}),
        ("NotebookEdit", {"notebook_path": "x.ipynb"}),
        ("WebFetch", {"url": "https://example.com"}),
        ("WebSearch", {"query": "client records"}),
        ("Agent", {"prompt": "read my files"}),
        ("Task", {"prompt": "read my files"}),
        ("mcp__drive__read_file", {"id": "x"}),
        ("LS", {"path": "/"}),
    ],
)
def test_every_other_tool_is_refused(sample: Path, name: str, fields: dict[str, Any]) -> None:
    start(sample)
    assert "sample book only" in denied(tool(name, sample, **fields))


@pytest.mark.parametrize("name", ["Skill", "TodoWrite", "AskUserQuestion"])
def test_tools_that_touch_no_file_go_ahead(sample: Path, name: str) -> None:
    start(sample)
    assert tool(name, sample) is None


def test_a_call_the_gate_cannot_read_is_refused(sample: Path) -> None:
    start(sample)
    assert "names no file" in denied(tool("Read", sample))
    with pytest.raises(gate.GateError):
        tool("Read", sample, file_path=["/etc/hosts"])


# ---- in a gated session: prompts -------------------------------------------------------------------------------


def test_a_household_outside_the_sample_book_is_refused_at_the_prompt(sample: Path) -> None:
    out = call("prompt", {"prompt": "/indus-casebook:reconciliation-as-of HH-0001", "cwd": str(sample)}, sample)
    assert out == {
        "decision": "block",
        "reason": "HH-0001 is not in the sample book. "
        "The indus-casebook plugin works on its sample households only: HH-1204, HH-5271.",
    }
    assert gate.is_gated(SESSION)
    later = call("prompt", {"prompt": "now do HH-0001 and HH-0002", "cwd": str(sample)}, sample)
    assert later is not None and later["reason"].startswith("HH-0001, HH-0002 are not in the sample book")
    assert call("prompt", {"prompt": "now do HH-1204", "cwd": str(sample)}, sample) is None


def test_a_file_mention_outside_the_sample_book_is_refused(sample: Path, outside: Path) -> None:
    start(sample)
    out = call("prompt", {"prompt": f"use @{outside} too", "cwd": str(sample)}, sample)
    assert out is not None and out["decision"] == "block"
    assert "loads no file of yours" in out["reason"]
    inside = "households/HH-5271/custodian/positions.csv"
    assert call("prompt", {"prompt": f"check @{inside}", "cwd": str(sample)}, sample) is None
    assert call("prompt", {"prompt": "mail ann@example.com", "cwd": str(sample)}, sample) is None


# ---- in a gated session: the answer starts with the notice ------------------------------------------------------


@pytest.mark.parametrize("answer", [f"{NOTICE}\n\nNo discrepancy.", f"> **{NOTICE[:40]}**{NOTICE[40:]}\n\nSources: …"])
def test_an_answer_starting_with_the_notice_ends(sample: Path, answer: str) -> None:
    start(sample)
    assert call("stop", {"last_assistant_message": answer, "stop_hook_active": False}, sample) is None


@pytest.mark.parametrize("answer", ["No discrepancy.", f"No discrepancy.\n\n{NOTICE}", NOTICE[:60], ""])
def test_an_answer_without_the_notice_first_is_sent_back(sample: Path, answer: str) -> None:
    start(sample)
    out = call("stop", {"last_assistant_message": answer, "stop_hook_active": False}, sample)
    assert out is not None and out["decision"] == "block"
    assert out["reason"].endswith(NOTICE)


def test_an_answer_sent_back_once_still_shows_the_advisor_the_notice(sample: Path) -> None:
    start(sample)
    out = call("stop", {"last_assistant_message": "No discrepancy.", "stop_hook_active": True}, sample)
    assert out == {"systemMessage": NOTICE}


def test_the_answer_is_read_from_the_transcript_when_the_hook_does_not_give_it(sample: Path, tmp_path: Path) -> None:
    def entry(kind: str, content: Any) -> str:
        return json.dumps({"type": kind, "message": {"role": kind, "content": content}})

    transcript = tmp_path / "t.jsonl"
    lines = [
        entry("user", "/indus-casebook:reconciliation-as-of HH-5271"),
        entry("assistant", [{"type": "text", "text": NOTICE}, {"type": "tool_use", "name": "Read"}]),
        entry("user", [{"type": "tool_result", "content": "rows"}]),
        entry("assistant", [{"type": "text", "text": "No discrepancy."}]),
        "not json",
    ]
    transcript.write_text("\n".join(lines))
    start(sample)
    sent_back = call("stop", {"transcript_path": str(transcript), "stop_hook_active": False}, sample)
    assert sent_back is not None and sent_back["decision"] == "block"
    transcript.write_text("\n".join([*lines[:3], entry("assistant", [{"type": "text", "text": f"{NOTICE}\n\nOK"}])]))
    assert call("stop", {"transcript_path": str(transcript), "stop_hook_active": False}, sample) is None


# ---- failing closed --------------------------------------------------------------------------------------------


def test_a_gated_session_with_no_readable_sample_book_refuses_everything(sample: Path) -> None:
    start(sample)
    (sample / "manifest.json").unlink()
    code, _, err = run_hook(["gate.py", "tool"], {"tool_name": "Read", "tool_input": {"file_path": "x"}}, sample)
    assert code == 2 and "cannot be read" in err
    code, _, _ = run_hook(["gate.py", "prompt"], {"prompt": "go on"}, sample)
    assert code == 2


def test_a_plugin_skill_with_no_readable_sample_book_is_refused(sample: Path) -> None:
    (sample / "NOTICE.txt").unlink()
    code, _, err = run_hook(["gate.py", "tool"], {"tool_name": "Skill", "tool_input": {"skill": "tax-lot-rmd"}}, sample)
    assert code == 2 and "cannot be read" in err


def run_hook(argv: list[str], data: dict[str, Any], book: Path) -> tuple[int, str, str]:
    return gate.main(argv, json.dumps({"session_id": SESSION, "cwd": str(book), **data}), book)


def test_main_reports_its_usage_and_ignores_unreadable_input() -> None:
    assert gate.main(["gate.py"], "{}")[0] == 2
    assert gate.main(["gate.py", "nothing"], "{}")[0] == 2
    assert gate.main(["gate.py", "tool"], "not json")[0] == 0
    assert gate.main(["gate.py", "tool"], "[1]")[0] == 0


# ---- the program as Claude Code runs it ------------------------------------------------------------------------


def _pythons() -> list[str]:
    """The test's own Python with no site packages, and the Mac's own python3 (3.9) where there is one."""
    found = [sys.executable]
    if Path("/usr/bin/python3").is_file():
        found.append("/usr/bin/python3")
    return found


@pytest.mark.parametrize("python", _pythons())
def test_the_program_runs_on_the_standard_library_alone(python: str, state: Path, outside: Path) -> None:
    """Run as hooks.json runs it, with no site packages: the real plugin's sample book, a skill that gates the
    session, then a read outside the book refused."""
    environment = {**os.environ, "CLAUDE_PLUGIN_DATA": str(state)}

    def hook(event: str, data: dict[str, Any]) -> subprocess.CompletedProcess[str]:
        payload = json.dumps({"session_id": "subprocess", "cwd": str(ROOT), **data})
        command = [python, "-I", "-S", str(GATE), event]
        return subprocess.run(command, input=payload, capture_output=True, text=True, env=environment, check=False)

    assert hook("tool", {"tool_name": "Bash", "tool_input": {"command": "ls"}}).stdout == ""
    started = hook("tool", {"tool_name": "Skill", "tool_input": {"skill": "indus-casebook:reconciliation-as-of"}})
    assert started.returncode == 0, started.stderr
    refused = hook("tool", {"tool_name": "Read", "tool_input": {"file_path": str(outside)}})
    assert refused.returncode == 0, refused.stderr
    assert json.loads(refused.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    inside = ROOT / "plugin" / "book" / "manifest.json"
    assert hook("tool", {"tool_name": "Read", "tool_input": {"file_path": str(inside)}}).stdout == ""
