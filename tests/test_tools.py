from importlib.metadata import distributions
from pathlib import Path

import pytest

from tools.check_licences import main as licence_main
from tools.check_licences import problems
from tools.check_no_float import float_uses
from tools.check_no_float import main as float_main


def plant_package(root: Path, name: str, *lines: str) -> Path:
    info = root / f"{name}-1.0.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text("\n".join(["Metadata-Version: 2.4", f"Name: {name}", "Version: 1.0", *lines]) + "\n")
    return root


@pytest.mark.parametrize(
    "declaration",
    [
        "License-Expression: GPL-3.0-only",
        "License-Expression: AGPL-3.0-or-later",
        "License-Expression: MIT AND GPL-2.0-or-later",
        # Reviewer B, slice 1 round 1, H1: grouping was ignored and this passed.
        "License-Expression: GPL-3.0-only AND (MIT OR Apache-2.0)",
        "License-Expression: (GPL-2.0-only OR AGPL-3.0-only) AND MIT",
        "License-Expression: GPL-2.0-only WITH Classpath-exception-2.0",
        "License-Expression: MIT AND (",
        "Classifier: License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Classifier: License :: OSI Approved :: GNU Affero General Public License v3",
        "License: GNU General Public License, version 2",
        "License: GPLv3",
    ],
)
def test_a_planted_gpl_package_fails_the_licence_check(tmp_path: Path, declaration: str) -> None:
    site = plant_package(tmp_path, "copyleft-thing", declaration)
    assert problems(distributions(path=[str(site)])) != []
    assert licence_main(["--path", str(site)]) == 1


@pytest.mark.parametrize(
    "declaration",
    [
        "License-Expression: MIT",
        "License-Expression: MIT OR GPL-2.0-only",
        "License-Expression: (MIT OR GPL-2.0-only) AND Apache-2.0",
        "License-Expression: (GPL-3.0-only AND MIT) OR BSD-3-Clause",
        "License-Expression: LGPL-3.0-or-later",
        "Classifier: License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)",
        "License: BSD-3-Clause",
    ],
)
def test_permissive_and_lesser_licences_pass(tmp_path: Path, declaration: str) -> None:
    site = plant_package(tmp_path, "fine-thing", declaration)
    assert problems(distributions(path=[str(site)])) == []


def test_a_package_with_no_licence_fails(tmp_path: Path) -> None:
    site = plant_package(tmp_path, "mystery")
    assert problems(distributions(path=[str(site)])) == [
        "mystery: declares no licence; check it by hand before adding it"
    ]


@pytest.mark.parametrize("name", ["tenforty", "policyengine-us", "PolicyEngine_US"])
def test_known_offenders_fail_by_name_whatever_they_declare(tmp_path: Path, name: str) -> None:
    site = plant_package(tmp_path, name, "License-Expression: MIT")
    assert len(problems(distributions(path=[str(site)]))) == 1


def test_the_installed_environment_passes_the_licence_check() -> None:
    assert licence_main([]) == 0


@pytest.mark.parametrize(
    "source", ["x = 1.5\n", "y = float(z)\n", "def f(a: float) -> None: ...\n", "rate: float = 0\n"]
)
def test_float_is_refused_in_money_code(source: str) -> None:
    assert float_uses(source, "money.py")


def test_decimal_code_passes_the_float_check() -> None:
    assert float_uses("from decimal import Decimal\nx = Decimal('1.5')\n", "money.py") == []


def test_the_money_packages_hold_no_float() -> None:
    assert float_main(["src/casebook/model", "src/casebook/replay"]) == 0


def test_every_tax_file_but_the_tax_calculator_boundary_holds_no_float() -> None:
    assert float_main(["src/casebook/tax", "--except", "src/casebook/tax/crosscheck.py"]) == 0
    # The boundary itself is where Tax-Calculator's floats are; without the exception the check fails.
    assert float_main(["src/casebook/tax"]) == 1


def test_an_exception_names_one_existing_file_only(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("RATE = 0.01\n")
    (tmp_path / "other.py").write_text("SHARE = 0.5\n")
    assert float_main([str(tmp_path), "--except", str(tmp_path / "bad.py")]) == 1
    (tmp_path / "other.py").unlink()
    assert float_main([str(tmp_path), "--except", str(tmp_path / "bad.py")]) == 0
    assert float_main([str(tmp_path), "--except", str(tmp_path / "renamed.py")]) == 1


def test_the_float_check_fails_on_a_planted_float(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("RATE = 0.01\n")
    assert float_main([str(tmp_path)]) == 1
