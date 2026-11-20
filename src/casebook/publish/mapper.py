"""Map a run's record and transcript to what may be published: real tickers and security names back to aliases,
and every home-folder path on the machine that ran it to a path relative to the repo or a placeholder."""

import json
import re
import tempfile
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from typing import Any

from casebook.published_text import decoded_blob
from casebook.securities.master import load_master
from casebook.securities.scan import TickerFinder, default_scan


class MappingError(RuntimeError):
    """A real ticker or security name survived mapping, so the record cannot be published."""


def _flexible(phrase: str) -> str:
    return r"\s+".join(map(re.escape, phrase.split()))


def alias_mapper() -> Callable[[str], str]:
    master = load_master()
    raw = json.loads((files("casebook.securities") / "real_names.json").read_text(encoding="utf-8"))
    by_ticker = {s.real_ticker: s.alias for s in master}
    names = sorted(
        ((name, by_ticker[ticker]) for ticker, ns in raw["names"].items() for name in ns),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
    named = [(re.compile(rf"(?<![A-Za-z0-9]){_flexible(n)}(?![A-Za-z0-9])", re.IGNORECASE), a) for n, a in names]
    issuers = [
        (re.compile(rf"(?<![A-Za-z0-9]){_flexible(n)}(?![A-Za-z0-9])", re.IGNORECASE), a)
        for n, a in raw["issuers"].items()
    ]
    tickers = TickerFinder(master)

    def map_text(text: str) -> str:
        for pattern, alias in named + issuers:
            text = pattern.sub(alias, text)
        parts: list[str] = []
        at = 0
        for match in tickers.find(text):
            parts += [text[at : match.start], by_ticker[match.ticker]]
            at = match.end
        return "".join(parts) + text[at:]

    return map_text


OMITTED = "<attachment omitted from the published record: the published book holds this file under aliases>"


def _walk(value: Any, map_text: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        # A file the run read, carried as base64 (a statement PDF, say), cannot be mapped in place.
        return OMITTED if decoded_blob(value) is not None else map_text(value)
    if isinstance(value, dict):
        return {map_text(str(k)): _walk(v, map_text) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v, map_text) for v in value]
    return value


def map_to_aliases(value: Any) -> Any:
    """Every string in a record or transcript, mapped; refused if a real identifier remains."""
    mapped = _walk(value, alias_mapper())
    leaks = default_scan().find(json.dumps(mapped, ensure_ascii=False))
    if leaks:
        raise MappingError(f"real identifiers remain after mapping: {sorted({h.identifier for h in leaks})}")
    return mapped


# Home-folder paths (the owner's choice 5(a), docs/decisions/2026-11-19-slice16-release-choices.md): a path inside the
# repo is published relative to it ("out/real/0.0.1", "skills/indus-advisor"); one outside it as a placeholder that
# names its role, never the user's name. Every hash a record keeps is of the files, not their paths, and stays.
PRIVATE_PLACEHOLDER = "<private>"
WORKSPACE_PLACEHOLDER = "<workspace>"
TEMP_PLACEHOLDER = "<temp>"
HOME_PLACEHOLDER = "<home>"
# The CLI's own folder for a session started elsewhere than a run workspace, under `~/.claude/projects/`.
CLI_PROJECT_PLACEHOLDER = "<cli-project>"
# A run's workspace, as `run_task` makes it: `tempfile.mkdtemp(prefix=...)` in the temp folder.
WORKSPACE_PREFIX = "casebook-workspace-"
_PATH_CHARS = "A-Za-z0-9._-"
# A path's root starts where no path character comes before it and ends where none follows, a full stop ending a
# sentence aside: never inside a longer name (the repo's own name is the start of the private folder's,
# "indus-casebook-private").
_START = rf"(?<![{_PATH_CHARS}])"
_END = rf"(?![{_PATH_CHARS}]*[A-Za-z0-9_-])"
# The temp folders a run's paths may sit in, wherever its machine keeps them: macOS's per-user folder, as the system
# names it and as it resolves, and the usual Unix ones.
_TEMP_ROOTS = (r"(?:/private)?/var/folders/[A-Za-z0-9_]+/[A-Za-z0-9_+-]+/[A-Za-z0-9]", r"(?:/private)?/(?:var/)?tmp")
_HOME_ROOTS = (rf"/Users/[{_PATH_CHARS}]+", rf"/home/[{_PATH_CHARS}]+", r"/root")
# The CLI keeps a session's files under `~/.claude/projects/<its working folder, every other character a dash>`.
_CLI_PROJECT = re.compile(rf"(?<=\.claude/projects/)-[A-Za-z0-9-]+{_END}")
_CLI_WORKSPACE = re.compile(rf"-{WORKSPACE_PREFIX}[a-z0-9-]+$")


def _literal(path: Path) -> list[str]:
    """A folder as given and as it resolves (macOS's /var is /private/var), each once."""
    return list(dict.fromkeys(p.as_posix().rstrip("/") for p in (path, path.resolve())))


def _alternation(literals: list[str], patterns: tuple[str, ...] = ()) -> str:
    longest_first = sorted(set(literals), key=len, reverse=True)
    return "|".join([*map(re.escape, longest_first), *patterns])


def path_rewriter(repo: Path, private: Path | None) -> Callable[[str], str]:
    """The rewrite of home-folder paths in one string: the private folder first, then the repo, the run's
    workspace and any other temp folder, and last any home folder, each the longest match, so a folder inside
    another takes its own name (the tests' private folder is in the temp folder; the repo is in a home folder)."""
    private_forms = set(_literal(private)) if private else set[str]()
    owned = re.compile(rf"{_START}(?:{_alternation([*private_forms, *_literal(repo)])}){_END}/?")
    temp = re.compile(
        rf"{_START}(?:{_alternation(_literal(Path(tempfile.gettempdir())), _TEMP_ROOTS)})"
        rf"(?P<workspace>/{WORKSPACE_PREFIX}[a-z0-9_]+)?{_END}"
    )
    home = re.compile(rf"{_START}(?:{_alternation(_literal(Path.home()), _HOME_ROOTS)}){_END}")

    def owned_root(match: re.Match[str]) -> str:
        found = match.group(0)
        root = found.removesuffix("/")
        if root in private_forms:
            return PRIVATE_PLACEHOLDER + found[len(root) :]
        # The repo: what is inside it, relative to it; the repo itself, ".".
        return "" if found.endswith("/") else "."

    def in_temp(match: re.Match[str]) -> str:
        return WORKSPACE_PLACEHOLDER if match.group("workspace") else TEMP_PLACEHOLDER

    def cli_project(match: re.Match[str]) -> str:
        return WORKSPACE_PLACEHOLDER if _CLI_WORKSPACE.search(match.group(0)) else CLI_PROJECT_PLACEHOLDER

    def rewrite(text: str) -> str:
        if "/" not in text:
            return text
        text = _CLI_PROJECT.sub(cli_project, text)
        text = owned.sub(owned_root, text)
        text = temp.sub(in_temp, text)
        return home.sub(HOME_PLACEHOLDER, text)

    return rewrite


def without_home_paths(value: Any, rewrite: Callable[[str], str]) -> Any:
    """Every string in a record or transcript event, keys too, with its home-folder paths rewritten; nothing else
    changes."""
    if isinstance(value, str):
        return rewrite(value)
    if isinstance(value, dict):
        return {rewrite(str(k)): without_home_paths(v, rewrite) for k, v in value.items()}
    if isinstance(value, list):
        return [without_home_paths(v, rewrite) for v in value]
    return value
