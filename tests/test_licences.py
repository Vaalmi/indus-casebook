"""docs/PLAN.md, slice 7: the dependency check passes with Tax-Calculator installed, and fails if PolicyEngine or
`tenforty` is added, whatever licence they declare."""

from importlib.metadata import distribution, distributions
from pathlib import Path

import pytest

from tools.check_licences import main as licence_main
from tools.check_licences import problems


def plant_package(root: Path, name: str, declaration: str) -> Path:
    info = root / f"{name}-1.0.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.4\nName: {name}\nVersion: 1.0\n{declaration}\n")
    return root


def test_the_check_passes_with_tax_calculator_installed() -> None:
    assert distribution("taxcalc").version == "6.9.1"
    assert licence_main([]) == 0


@pytest.mark.parametrize("name", ["policyengine-us", "policyengine-core", "tenforty"])
def test_adding_a_refused_calculator_fails_the_check(tmp_path: Path, name: str) -> None:
    site = plant_package(tmp_path, name, "License-Expression: MIT")
    (found,) = problems(distributions(path=[str(site)]))
    assert found.startswith(f"{name}: refused by name")
    assert licence_main(["--path", str(site)]) == 1
