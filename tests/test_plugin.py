"""The plugin as it installs from the repo (docs/PLAN.md, slice 15): the four approved skills byte for byte, the sample
book, the household gate wired to every hook it needs, and nothing else that could load a file."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from casebook.model.archetypes import FREEZE_RECORD
from casebook.notice import NOTICE, contains_notice
from casebook.runner.config import tree_sha256
from tests.test_plugin_gate import gate

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin"
SKILLS = ("compliance-review", "meeting-follow-up", "reconciliation-as-of", "tax-lot-rmd")
APPROVED = ROOT / "skills" / "indus-advisor" / "skills"


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("skill", SKILLS)
def test_each_skill_ships_as_the_freeze_recorded_it(skill: str) -> None:
    """The owner's decision: the skills ship byte-identical, so the plugin's skill is the one the results measured."""
    recorded = _json(FREEZE_RECORD)["hashes"]
    assert isinstance(recorded, dict)
    assert tree_sha256(PLUGIN / "skills" / skill) == recorded[f"skill {skill}"]
    assert tree_sha256(PLUGIN / "skills" / skill) == tree_sha256(APPROVED / skill)


def test_the_plugin_ships_the_four_skills_and_no_other() -> None:
    assert sorted(p.name for p in (PLUGIN / "skills").iterdir()) == list(SKILLS)
    assert frozenset(SKILLS) == gate.SKILLS


def test_the_plugin_is_named_as_the_gate_and_the_marketplace_name_it() -> None:
    manifest = _json(PLUGIN / ".claude-plugin" / "plugin.json")
    marketplace = _json(ROOT / ".claude-plugin" / "marketplace.json")
    assert manifest["name"] == gate.PLUGIN
    plugins = marketplace["plugins"]
    assert isinstance(plugins, list)
    assert [(p["name"], p["source"]) for p in plugins] == [(gate.PLUGIN, "./plugin")]


def test_the_plugin_offers_no_way_to_load_other_files() -> None:
    """The plan's criterion: "offers no way to load other files". No MCP server, command, agent, output style,
    LSP server or executable folder; the only program is the gate."""
    names = {p.name for p in PLUGIN.iterdir()}
    assert names == {".claude-plugin", "LICENSE", "LICENSE-DATA", "README.md", "book", "hooks", "skills"}
    assert sorted(p.name for p in (PLUGIN / ".claude-plugin").iterdir()) == ["plugin.json"]
    manifest = _json(PLUGIN / ".claude-plugin" / "plugin.json")
    assert not {"mcpServers", "commands", "agents", "hooks", "lspServers", "outputStyles"} & set(manifest)
    assert sorted(p.name for p in (PLUGIN / "hooks").iterdir() if p.name != "__pycache__") == [
        "gate.py",
        "hooks.json",
    ]
    programs = [p for p in PLUGIN.rglob("*") if p.is_file() and p.suffix in (".py", ".sh", ".js", ".mjs", ".exe")]
    assert [p.relative_to(PLUGIN).as_posix() for p in programs] == ["hooks/gate.py"]


def test_every_hook_the_gate_needs_runs_it() -> None:
    hooks = _json(PLUGIN / "hooks" / "hooks.json")["hooks"]
    assert isinstance(hooks, dict)
    wired: dict[str, tuple[str, str]] = {}
    for event, groups in hooks.items():
        for group in groups:
            for hook in group["hooks"]:
                assert hook["type"] == "command"
                assert hook["command"] == "python3"
                script, argument = hook["args"]
                assert script == "${CLAUDE_PLUGIN_ROOT}/hooks/gate.py"
                wired[event] = (group.get("matcher", "*"), argument)
    assert wired == {
        "UserPromptSubmit": ("*", "prompt"),
        "PreToolUse": ("*", "tool"),
        "PostToolUse": ("Skill", "skill"),
        "Stop": ("*", "stop"),
    }
    assert set(gate.HOOKS) == {argument for _, argument in wired.values()}
    # A tool call the gate cannot judge, because python3 is missing or the program fails, is refused, not let by.
    (tool,) = hooks["PreToolUse"][0]["hooks"]
    assert tool["onFailure"] == "block"


def test_the_gate_imports_the_standard_library_only_and_reads_as_python_3_9() -> None:
    """macOS's own python3 is 3.9; the advisor's machine has nothing of this repo but the plugin folder."""
    import ast

    source = (PLUGIN / "hooks" / "gate.py").read_text(encoding="utf-8")
    tree = ast.parse(source, feature_version=(3, 9))
    imported = {
        name.split(".")[0]
        for node in ast.walk(tree)
        for name in (
            [a.name for a in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
            if isinstance(node, ast.ImportFrom)
            else []
        )
    }
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}


def test_the_plugin_s_readme_opens_with_the_notice_and_its_licences_are_the_repo_s() -> None:
    readme = (PLUGIN / "README.md").read_text(encoding="utf-8")
    assert contains_notice(readme.split("\n\n")[0])
    assert re.search(r"python3", readme)
    for name in ("LICENSE", "LICENSE-DATA"):
        assert (PLUGIN / name).read_bytes() == (ROOT / name).read_bytes()


# ---- the gate on the real sample book --------------------------------------------------------------------------


def test_the_gate_reads_the_shipped_sample_book() -> None:
    book = gate.SampleBook()
    manifest = _json(PLUGIN / "book" / "manifest.json")
    households = manifest["households"]
    assert isinstance(households, list)
    assert book.households == tuple(h["household_id"] for h in households)
    assert len(book.households) == 20
    assert book.notice == NOTICE


def test_a_path_outside_the_shipped_book_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The plan's criterion, on the plugin as it ships: a gated session reads every file the sample book's manifest
    lists, and is refused a path outside the book, a household it does not list, and the repo's own book."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    book = PLUGIN / "book"
    session = {"session_id": "shipped", "cwd": str(ROOT)}
    skill = {"tool_name": "Skill", "tool_input": {"skill": "indus-casebook:tax-lot-rmd"}}
    assert gate.on_tool({**session, **skill}) is None
    files = _json(book / "manifest.json")["files"]
    assert isinstance(files, dict) and files
    for name in files:
        assert gate.on_tool({**session, "tool_name": "Read", "tool_input": {"file_path": str(book / name)}}) is None
    refused = [
        ROOT / "README.md",
        ROOT / "out" / "book" / "0.0.1" / "sealed" / "households.json",
        ROOT / "published" / "keys",
        book / "households" / "HH-0120" / "crm" / "crm.json",
        book / ".." / "hooks" / "gate.py",
        Path.home() / "Documents" / "clients.csv",
    ]
    for path in refused:
        out = gate.on_tool({**session, "tool_name": "Read", "tool_input": {"file_path": str(path)}})
        assert out is not None and out["hookSpecificOutput"]["permissionDecision"] == "deny", path


def test_the_shipped_gate_runs_as_claude_code_runs_it(tmp_path: Path) -> None:
    command = [sys.executable, "-I", "-S", str(PLUGIN / "hooks" / "gate.py"), "prompt"]
    payload = json.dumps({"session_id": "cli", "cwd": str(ROOT), "prompt": "/indus-casebook:tax-lot-rmd HH-5271"})
    run = subprocess.run(
        command,
        input=payload,
        capture_output=True,
        text=True,
        env={"CLAUDE_PLUGIN_DATA": str(tmp_path), "PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert run.returncode == 0, run.stderr
    context = json.loads(run.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "HH-5271" in context and NOTICE in context
