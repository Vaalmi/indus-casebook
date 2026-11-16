"""The one configuration every arm shares. Only the instruction differs between arms."""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

ARMS = ("basic", "checklist", "skill")
REPO = Path(__file__).resolve().parents[3]
INSTRUCTIONS: dict[str, Path | None] = {
    "basic": None,
    "checklist": REPO / "checklist" / "indus-checklist",
    "skill": REPO / "skills" / "indus-advisor",
}
LOADING_TOOL = "Skill"
# The environment a run sees: enough for the CLI to find itself and its sign-in, nothing more.
ENVIRONMENT_KEYS = ("HOME", "LANG", "LOGNAME", "PATH", "TMPDIR", "USER")


@dataclass(frozen=True)
class SharedConfig:
    model: str = "claude-opus-5-5"
    # The task's file tools, plus Skill: the route a user's installed skill or checklist loads by.
    # Every arm has it; only the basic arm has nothing of ours to load with it.
    tools: tuple[str, ...] = ("Read", "Glob", "Grep", "Skill")
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
