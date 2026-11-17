"""The one configuration every arm shares. Only the instruction differs between arms."""

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

ARMS = ("basic", "checklist", "skill")
REPO = Path(__file__).resolve().parents[3]
INSTRUCTIONS: dict[str, Path | None] = {
    "basic": None,
    "checklist": REPO / "checklist" / "indus-checklist",
    "skill": REPO / "skills" / "indus-advisor",
}
LOADING_TOOL = "Skill"
# The CRM sandbox's MCP server, and its tools as the CLI names them: a follow-up task allows them.
CRM_SERVER = "crm"
CRM_TOOLS = tuple(
    f"mcp__{CRM_SERVER}__{tool}"
    for tool in ("list_households", "read_household", "add_note", "add_activity", "mark_activity_done")
)
# The environment a run sees: enough for the CLI to find itself and its sign-in, nothing more.
ENVIRONMENT_KEYS = ("HOME", "LANG", "LOGNAME", "PATH", "TMPDIR", "USER")


@dataclass(frozen=True)
class SharedConfig:
    model: str = "claude-opus-5-5"
    # The owner's choice (16 November 2026). The CLI does not echo it, so the record's arguments are the evidence.
    effort: str = "high"
    # The task's file tools, plus Skill: the route a user's installed skill or checklist loads by.
    # Every arm has it; only the basic arm has nothing of ours to load with it.
    tools: tuple[str, ...] = ("Read", "Glob", "Grep", "Skill")
    # The CRM sandbox's tools a follow-up task allows, pre-approved with --allowedTools; none for any other task.
    crm_tools: tuple[str, ...] = ()
    max_turns: int = 40
    timeout_seconds: int = 900
    retries: int = 3
    flags: tuple[str, ...] = (
        "--restricted",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--permission-mode",
        "dontAsk",
        "--permission-prompts",
        "none",
        "--output-format",
        "stream-json",
        "--verbose",
    )

    def for_tools(self, allowed: tuple[str, ...]) -> "SharedConfig":
        """The configuration for a task that allows these tools: the CRM sandbox's, if it allows any of them."""
        return replace(self, crm_tools=tuple(t for t in CRM_TOOLS if t in allowed))

    def as_dict(self) -> dict[str, object]:
        """As it is stored in a run record: plain JSON, tuples as lists."""
        return json.loads(json.dumps(asdict(self)))

    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.as_dict(), sort_keys=True).encode()).hexdigest()


def tree_sha256(path: Path | None) -> str | None:
    """The hash of an instruction package: every file's path and bytes."""
    if path is None:
        return None
    digest = hashlib.sha256()
    for file in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(file.relative_to(path).as_posix().encode() + b"\0" + file.read_bytes() + b"\0")
    return digest.hexdigest()
