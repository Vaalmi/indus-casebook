"""The plugin's household gate (docs/SPEC.md, Rules: "the runner and the plugin accept only household IDs listed in
the book manifest. Nothing in the product reads a file from outside the book").

Claude Code runs this program for every hook the plugin registers (hooks/hooks.json), in every session of every
project once the plugin is installed. It does nothing until one of the plugin's four skills is used in a session
(the owner's decision of 19 November 2026, docs/decisions/2026-11-19-plugin-gate.md). From then on, in that session:

- it names the sample book and its households to Claude;
- it refuses a prompt naming a household the sample book's manifest does not list, or mentioning a file outside it;
- it allows Read, Glob and Grep inside the sample book only, and refuses every other tool that reads, writes, runs a
  command or reaches the web;
- it sends an answer back once if the answer does not start with the notice, and shows the notice to the advisor if
  the answer still lacks it.

Python's standard library only: the advisor's machine has nothing of this repo but the plugin folder.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

PLUGIN = "indus-casebook"
SKILLS = frozenset({"compliance-review", "meeting-follow-up", "reconciliation-as-of", "tax-lot-rmd"})
ROOT = Path(__file__).resolve().parent.parent
BOOK = ROOT / "book"
MANIFEST = "manifest.json"
METADATA = "metadata.json"
NOTICE_FILE = "NOTICE.txt"

READERS = frozenset({"Read", "Glob", "Grep"})
# Tools that neither read nor write a file, run a command or reach the web: left alone in a gated session.
HARMLESS = frozenset({"Skill", "TodoWrite", "AskUserQuestion"})
HOUSEHOLD = re.compile(r"\bHH-\d{4}\b")
MENTION = re.compile(r"(?:^|\s)@(\"[^\"]+\"|\S+)")
SKILL_COMMAND = re.compile(r"^\s*/(?:([\w.-]+):)?([\w.-]+)(?:\s|$)")
WILDCARD = re.compile(r"[*?\[{]")

JSON = dict[str, Any]


class GateError(Exception):
    """The gate cannot judge a call in a gated session (an unreadable sample book, a malformed input): it refuses."""


# ---- the sample book -------------------------------------------------------------------------------------------


class SampleBook:
    def __init__(self, root: Path = BOOK) -> None:
        self.root = root
        try:
            manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
            metadata = json.loads((root / METADATA).read_text(encoding="utf-8"))
            self.notice = (root / NOTICE_FILE).read_text(encoding="utf-8").strip()
            self.households: tuple[str, ...] = tuple(h["household_id"] for h in manifest["households"])
            self.scenario_date = str(metadata.get("scenario_date", ""))
        except (OSError, ValueError, KeyError, TypeError) as error:
            # The error's kind, never its text: Claude Code reads a plugin's prompt hook whose message says a file
            # is missing as the hook failing, and lets the prompt through.
            raise GateError(f"the sample book at {root} cannot be read ({type(error).__name__})") from error
        if not self.notice or not self.households:
            raise GateError(f"the sample book at {root} has no notice or no households")

    def holds(self, path: Path) -> bool:
        """Whether `path`, every link in it followed, is a file or folder of the sample book, and, if it is inside a
        household's folder, whether the manifest lists that household."""
        real = Path(os.path.realpath(path))
        root = Path(os.path.realpath(self.root))
        if real != root and root not in real.parents:
            return False
        parts = real.relative_to(root).parts
        return not (len(parts) >= 2 and parts[0] == "households" and parts[1] not in self.households)

    def context(self) -> str:
        households = ", ".join(self.households)
        return (
            f"The {PLUGIN} plugin is in use, so this session works on its sample book only: invented households, "
            f"no real client's records. The sample book is the folder {self.root}. Its households are {households}. "
            f"Each household's files are in {self.root}/households/<household ID>/, in four source sets: custodian, "
            f"portfolio, crm and documents; the security names and synthetic prices are in {self.root}/securities/. "
            f"Every file is listed in {self.root}/{MANIFEST}. The records stand as of {self.scenario_date}. Read "
            "only these files, with Read (or Glob and Grep where you have them): Bash, every other tool, and any file "
            "outside the sample book are refused for the rest of this session. If the "
            "advisor has not said which household, ask, listing the households above. If they name one the sample "
            "book does not hold, say so and list the ones it does; never load their own files. Start every answer "
            f"with this notice, word for word: {self.notice} After the notice, name the sample-book files you used."
        )


# ---- the session's state ---------------------------------------------------------------------------------------


def _state_dir() -> Path:
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    return Path(data) if data else Path(tempfile.gettempdir()) / f"{PLUGIN}-gate"


def _state_file(session: str) -> Path:
    return _state_dir() / "sessions" / f"{hashlib.sha256(session.encode()).hexdigest()[:32]}.json"


def is_gated(session: str) -> bool:
    return bool(session) and _state_file(session).is_file()


def gate_session(session: str) -> None:
    if not session:
        raise GateError("a plugin skill was used in a session with no ID, so the gate cannot hold it")
    path = _state_file(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"gated": True}), encoding="utf-8")


# ---- recognising the plugin's skills ---------------------------------------------------------------------------


def is_plugin_skill(name: str) -> bool:
    plugin, _, skill = name.strip().lstrip("/").rpartition(":")
    return skill in SKILLS and plugin in ("", PLUGIN)


def skill_in_prompt(prompt: str) -> bool:
    match = SKILL_COMMAND.match(prompt)
    return match is not None and match.group(2) in SKILLS and match.group(1) in (None, PLUGIN)


# ---- judging a call --------------------------------------------------------------------------------------------


def _string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise GateError(f"the field {field} is not text")
    return value


def _where(value: str, cwd: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else cwd / path


def _fixed_prefix(pattern: str) -> tuple[str, str]:
    """A glob pattern split into its leading folders without a wildcard and the rest."""
    parts = pattern.split("/")
    for index, part in enumerate(parts):
        if WILDCARD.search(part):
            return "/".join(parts[:index]), "/".join(parts[index:])
    return "/".join(parts[:-1]), parts[-1]


def _pattern_problem(pattern: str, base: Path, book: SampleBook, field: str) -> str | None:
    if ".." in Path(pattern).parts or "~" in pattern:
        return f"{field} {pattern!r} climbs out of the folder it searches"
    fixed, _ = _fixed_prefix(pattern)
    if fixed and not book.holds(_where(fixed, base)):
        return f"{field} {pattern!r} reaches outside the sample book"
    return None


def tool_problem(tool: str, tool_input: JSON, cwd: Path, book: SampleBook) -> str | None:
    """Why a tool call in a gated session is refused, or None if it may go ahead."""
    if tool in HARMLESS:
        return None
    if tool not in READERS:
        return (
            f"{tool} is off in a session that uses the {PLUGIN} plugin, which reads its sample book only: "
            f"read its files with Read; {book.root / MANIFEST} lists them"
        )
    if tool == "Read":
        target = _string(tool_input.get("file_path"), "file_path")
        if not target:
            return "Read names no file"
        return None if book.holds(_where(target, cwd)) else f"{target} is not in the sample book"
    where = _string(tool_input.get("path"), "path")
    base = _where(where, cwd) if where else cwd
    if not book.holds(base):
        return f"{where or cwd} is not in the sample book; search {book.root} instead"
    pattern = _string(tool_input.get("pattern" if tool == "Glob" else "glob"), "pattern")
    if pattern:
        return _pattern_problem(pattern, base, book, "the pattern" if tool == "Glob" else "the glob")
    return None


def prompt_problem(prompt: str, cwd: Path, book: SampleBook) -> str | None:
    unknown = sorted({h for h in HOUSEHOLD.findall(prompt) if h not in book.households})
    if unknown:
        return (
            f"{', '.join(unknown)} {'is' if len(unknown) == 1 else 'are'} not in the sample book. "
            f"The {PLUGIN} plugin works on its sample households only: {', '.join(book.households)}."
        )
    for mention in MENTION.findall(prompt):
        target = mention.strip('"')
        if not book.holds(_where(target, cwd)):
            return f"@{target} is outside the sample book; the {PLUGIN} plugin loads no file of yours."
    return None


# ---- the answer and its notice ---------------------------------------------------------------------------------


def _normalize(text: str) -> str:
    # As casebook.notice: Markdown emphasis, quoting and line wrapping are presentation, not wording.
    return " ".join(re.sub(r"[*_>#]", " ", text).split())


def starts_with_notice(answer: str, notice: str) -> bool:
    return _normalize(answer).startswith(_normalize(notice))


def _texts(content: object) -> list[str]:
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    blocks = cast(list[object], content)
    return [
        str(cast(dict[str, object], b).get("text", ""))
        for b in blocks
        if isinstance(b, dict) and cast(dict[str, object], b).get("type") == "text"
    ]


def last_answer(transcript: Path) -> str:
    """The text Claude wrote after the last prompt or tool result (both are user entries in the transcript): the
    answer this Stop ends."""
    answer: list[str] = []
    for line in transcript.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        record = cast(dict[str, object], entry)
        message = record.get("message")
        content = cast(dict[str, object], message).get("content") if isinstance(message, dict) else None
        if record.get("type") == "user" and not record.get("isMeta"):
            answer = []
        elif record.get("type") == "assistant":
            answer += _texts(content)
    return "\n".join(t for t in answer if t.strip())


# ---- the hooks -------------------------------------------------------------------------------------------------


def _deny(reason: str) -> JSON:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _context(event: str, book: SampleBook) -> JSON:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": book.context()}}


def on_prompt(data: JSON, book_root: Path = BOOK) -> JSON | None:
    session, prompt = str(data.get("session_id", "")), str(data.get("prompt", ""))
    starting = skill_in_prompt(prompt)
    if not starting and not is_gated(session):
        return None
    book = SampleBook(book_root)
    problem = prompt_problem(prompt, Path(str(data.get("cwd") or Path.cwd())), book)
    if starting:
        gate_session(session)
    if problem:
        return {"decision": "block", "reason": problem}
    return _context("UserPromptSubmit", book) if starting else None


def on_tool(data: JSON, book_root: Path = BOOK) -> JSON | None:
    session, tool = str(data.get("session_id", "")), str(data.get("tool_name", ""))
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    fields = cast(JSON, tool_input)
    if tool == "Skill" and is_plugin_skill(str(fields.get("skill", ""))):
        SampleBook(book_root)  # a plugin skill with no readable sample book is refused here, before it loads
        gate_session(session)
        return None
    if not is_gated(session):
        return None
    problem = tool_problem(tool, fields, Path(str(data.get("cwd") or Path.cwd())), SampleBook(book_root))
    return _deny(problem) if problem else None


def on_skill(data: JSON, book_root: Path = BOOK) -> JSON | None:
    tool_input = data.get("tool_input")
    skill = str(cast(JSON, tool_input).get("skill", "")) if isinstance(tool_input, dict) else ""
    if data.get("tool_name") != "Skill" or not is_plugin_skill(skill):
        return None
    return _context("PostToolUse", SampleBook(book_root))


def on_stop(data: JSON, book_root: Path = BOOK) -> JSON | None:
    if not is_gated(str(data.get("session_id", ""))):
        return None
    book = SampleBook(book_root)
    answer = data.get("last_assistant_message")
    if not isinstance(answer, str):
        transcript = data.get("transcript_path")
        answer = last_answer(Path(str(transcript))) if transcript else ""
    if starts_with_notice(answer, book.notice):
        return None
    if data.get("stop_hook_active"):
        # Sent back once already: the advisor sees the notice from the gate itself rather than not at all.
        return {"systemMessage": book.notice}
    return {
        "decision": "block",
        "reason": f"Your answer must start with this notice, word for word, then give the answer: {book.notice}",
    }


HOOKS = {"prompt": on_prompt, "tool": on_tool, "skill": on_skill, "stop": on_stop}


def main(argv: list[str], stdin: str, book_root: Path = BOOK) -> tuple[int, str, str]:
    """The exit code, stdout and stderr for one hook call. A call the gate cannot judge in a gated session, or a
    plugin skill it cannot gate, is refused (exit 2); outside a gated session the gate stays out of the way."""
    if len(argv) != 2 or argv[1] not in HOOKS:
        return 2, "", f"usage: gate.py {'|'.join(HOOKS)}"
    try:
        data = json.loads(stdin)
        if not isinstance(data, dict):
            raise GateError("the hook's input is not a JSON object")
    except (ValueError, GateError) as error:
        return 0, "", f"{PLUGIN} gate: unreadable hook input ({error})"
    payload = cast(JSON, data)
    try:
        out = HOOKS[argv[1]](payload, book_root)
    except (GateError, OSError) as error:
        return 2, "", f"{PLUGIN} gate refused this: {error}"
    return 0, json.dumps(out) if out else "", ""


if __name__ == "__main__":
    code, out, err = main(sys.argv, sys.stdin.read())
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)
    sys.exit(code)
