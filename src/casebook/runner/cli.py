"""The only module that starts the CLI under test (docs/PLAN.md, import contract 3)."""

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from casebook.runner.config import ENVIRONMENT_KEYS, INSTRUCTIONS, SharedConfig

CLI_VARIABLE = "CASEBOOK_CLAUDE"
DEFAULT_CLI = "claude"


def cli_command() -> list[str]:
    """`claude`, or the stand-in that CASEBOOK_CLAUDE names (the checks never call a real model)."""
    return shlex.split(os.environ.get(CLI_VARIABLE, DEFAULT_CLI))


def run_environment() -> dict[str, str]:
    return {key: os.environ[key] for key in ENVIRONMENT_KEYS if key in os.environ}


def arguments(prompt: str, arm: str, config: SharedConfig) -> list[str]:
    """The full command line. The prompt is one argument; nothing from a fixture enters it."""
    args = [*cli_command(), "-p", prompt, *config.flags]
    args += ["--model", config.model, "--tools", ",".join(config.tools), "--max-turns", str(config.max_turns)]
    instruction = INSTRUCTIONS[arm]
    if instruction is not None:
        args += ["--plugin-dir", str(instruction)]
    return args


@dataclass(frozen=True)
class Completed:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    launch_error: str | None = None


def cli_version() -> str:
    try:
        done = subprocess.run([*cli_command(), "--version"], capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"unknown ({type(error).__name__}: {error})"
    return done.stdout.strip() or done.stderr.strip()


def start(args: list[str], workspace: Path, config: SharedConfig) -> Completed:
    try:
        done = subprocess.run(
            args,
            cwd=workspace,
            env=run_environment(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=config.timeout_seconds,
            check=False,
        )
    except OSError as error:
        return Completed(None, "", "", False, f"{type(error).__name__}: {error}")
    except subprocess.TimeoutExpired as expired:

        def text(value: bytes | str | None) -> str:
            return value.decode() if isinstance(value, bytes) else (value or "")

        return Completed(None, text(expired.stdout), text(expired.stderr), True)
    return Completed(done.returncode, done.stdout, done.stderr, False)
