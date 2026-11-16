"""The project's own rules: the import contracts, the licence files."""

import tomllib

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
