"""docs/PLAN.md, import contract 3: each outside program is reached through one module: the CLIs through
`runner/cli.py` and `graders/jury.py`, Tax-Calculator through `tax/crosscheck.py`."""

import ast

import pytest

from .conftest import ROOT

ALLOWED = {"src/casebook/runner/cli.py", "src/casebook/graders/jury.py"}
PROCESS_MODULES = {"subprocess", "pty", "multiprocessing"}
PROCESS_CALLS = {"system", "popen", "spawnl", "spawnv", "execv", "execve", "execvp", "fork", "create_subprocess_exec"}


def starts_a_process(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] in PROCESS_MODULES for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in PROCESS_MODULES:
            return True
        if isinstance(node, ast.Attribute) and node.attr in PROCESS_CALLS:
            return True
        if isinstance(node, ast.ImportFrom) and any(a.name in PROCESS_CALLS for a in node.names):
            return True
    return False


@pytest.mark.parametrize(
    "source",
    [
        "import subprocess",
        "from subprocess import run",
        "import os\nos.system('claude')",
        "import os\nos.popen('codex')",
        "from os import execvp",
        "import asyncio\nasyncio.create_subprocess_exec('agy')",
    ],
)
def test_the_detector_finds_each_way_to_start_a_program(source: str) -> None:
    assert starts_a_process(source)


def test_only_the_runner_cli_module_starts_a_process() -> None:
    starters = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src" / "casebook").rglob("*.py")
        if starts_a_process(path.read_text())
    }
    assert starters == ALLOWED


def imports_tax_calculator(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "taxcalc" for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "taxcalc":
            return True
    return False


@pytest.mark.parametrize("source", ["import taxcalc", "import taxcalc as tc", "from taxcalc import Calculator"])
def test_the_detector_finds_each_way_to_import_tax_calculator(source: str) -> None:
    assert imports_tax_calculator(source)


def test_only_the_crosscheck_module_imports_tax_calculator() -> None:
    importers = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src" / "casebook").rglob("*.py")
        if imports_tax_calculator(path.read_text())
    }
    assert importers == {"src/casebook/tax/crosscheck.py"}
