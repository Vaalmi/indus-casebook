"""The project's own rules: the import contracts, the licence files."""

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from .conftest import ROOT

PACKAGE = ROOT / "src" / "casebook"


def pyproject() -> dict[str, object]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_checks_are_forbidden_every_module_but_model() -> None:
    contracts = pyproject()["tool"]["importlinter"]["contracts"]  # type: ignore[index]
    contract = next(c for c in contracts if c["source_modules"] == ["casebook.checks"])  # type: ignore[union-attr]
    modules = {p.stem for p in PACKAGE.iterdir() if p.suffix == ".py" and p.stem != "__init__"}
    modules |= {p.name for p in PACKAGE.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    expected = {f"casebook.{m}" for m in modules - {"model", "checks"}}
    assert set(contract["forbidden_modules"]) == expected  # type: ignore[index]


def test_code_is_apache_2_and_data_is_cc_by_4() -> None:
    assert (ROOT / "LICENSE").read_text().split()[:4] == ["Apache", "License", "Version", "2.0,"]
    assert (
        (ROOT / "LICENSE-DATA").read_text().startswith("Creative Commons Attribution 4.0 International Public License")
    )
    assert pyproject()["project"]["license"] == "Apache-2.0"  # type: ignore[index]


def test_the_hook_and_the_action_run_the_one_check_command() -> None:
    assert "make check" in (ROOT / ".githooks" / "pre-commit").read_text()
    workflow = (ROOT / ".github" / "workflows" / "check.yml").read_text()
    assert "make check" in workflow
    assert "push" in workflow


def lint_imports(package_root: Path, config: Path) -> subprocess.CompletedProcess[str]:
    """import-linter on a copy of the package, which goes ahead of the installed one on the path."""
    tool = Path(sys.executable).parent / "lint-imports"
    env = {**os.environ, "PYTHONPATH": str(package_root)}
    return subprocess.run(
        [str(tool), "--config", str(config)], cwd=config.parent, env=env, capture_output=True, text=True, check=False
    )


def test_a_key_that_imports_replay_breaks_the_keys_contract(tmp_path: Path) -> None:
    """docs/PLAN.md, slice 9: the contract passes, and fails when a key module imports `replay`."""
    src = tmp_path / "src"
    shutil.copytree(PACKAGE, src / "casebook", ignore=shutil.ignore_patterns("__pycache__", "*.pdf"))
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    kept = lint_imports(src, tmp_path / "pyproject.toml")
    assert kept.returncode == 0, kept.stdout + kept.stderr
    assert "keys and graders import no generator code KEPT" in kept.stdout

    (src / "casebook" / "keys" / "probe.py").write_text(
        '"""A key that reads the ledger."""\n\nimport casebook.replay\n'
    )
    broken = lint_imports(src, tmp_path / "pyproject.toml")
    assert broken.returncode != 0
    assert "keys and graders import no generator code BROKEN" in broken.stdout
    assert "casebook.keys.probe -> casebook.replay" in broken.stdout
