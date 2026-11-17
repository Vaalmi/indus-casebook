"""The RMD sweep key (T-TAX-05) over the whole public book, and its fit with the list grader."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.graders.household_list import grade
from casebook.keys.rmd_sweep import RmdSweepKey, rmd_sweep_key
from casebook.tasks.fixtures import load_task_fixtures

from .conftest import built

# The households whose 2025 RMD was not met, each with its owner and the account short. Archetype 5's traps
# took the IRAs' RMDs from an IRA and nothing from the 401(k), whose RMD only the plan can pay; archetype 7's
# traps took nothing from an inherited IRA whose decedent died after the required beginning date.
MISSED = {
    "HH-0120": ("P-0120-1", "SYN-01200004"),
    "HH-0236": ("P-0236-1", "SYN-02360004"),
    "HH-0371": ("P-0371-1", "SYN-03710004"),
    "HH-0466": ("P-0466-1", "SYN-04660002"),
    "HH-0491": ("P-0491-1", "SYN-04910002"),
    "HH-0607": ("P-0607-1", "SYN-06070002"),
    "HH-0664": ("P-0664-1", "SYN-06640004"),
    "HH-0842": ("P-0842-1", "SYN-08420002"),
    "HH-5271": ("P-5271-1", "SYN-52710004"),
    # Archetype 7's featured trap, public since the freeze (book/scripted/archetype-7/expected.json): Samuel
    # Adeyemi, born 30 May 1974, inherited SYN-71260002 from Florence, born 11 February 1946, who died on 19 July
    # 2023, after her required beginning date of 1 April 2017. Samuel is 50 in 2024: 36.2, less 1 = 35.2. On 31
    # December 2024 the account held 169,999.61 + 149,777.00 + 49,878.30 + 9,000.00 cash = 378,654.91, / 35.2 =
    # 10,757.24, and in 2025 it paid only fees. Its twin HH-7683 owes no annual RMD (Carla died before her
    # required beginning date), and archetype 8's owners, born 1955 and 1956, are not yet 73.
    "HH-7126": ("P-7126-1", "SYN-71260002"),
}


@pytest.fixture(scope="module")
def key(full_book: Path) -> RmdSweepKey:
    return rmd_sweep_key(full_book)


def test_the_sweep_finds_every_unmet_rmd_in_the_book(full_book: Path, key: RmdSweepKey) -> None:
    assert key.checked == tuple(sorted(built(full_book)))
    assert dict(key.found) == MISSED
    assert key.unresolved == ()


def test_the_sweep_s_inherited_ira_shortfall_is_hand_worked(key: RmdSweepKey) -> None:
    # HH-0466: Zainab Aldana, born 4 November 1969, inherited SYN-04660002 from Rafaela Mahlangu, born 6 March
    # 1945, who died on 15 January 2022, after her required beginning date of 1 April 2016 (70½ on 6 September
    # 2015). Zainab is 54 in 2023: single life 32.5, less 2 = 30.5; Rafaela was 77 in 2022: 13.3, less 3 =
    # 10.3. On 31 December 2024 the account held 66,168.00 + 207,953.01 + 176,723.10 + 8,750.00 cash =
    # 459,594.11, / 30.5 = 15,068.66, and nothing was taken in 2025.
    (found,) = [r for h, r in key.missed if h == "HH-0466"]
    assert (found.rmd, found.taken, found.shortfall, str(found.deadline)) == (
        Decimal("15068.66"),
        Decimal("0"),
        Decimal("15068.66"),
        "2025-12-31",
    )


def test_the_sweep_clears_the_first_year_twin_that_paid_in_the_next_year(key: RmdSweepKey) -> None:
    # HH-0637's owner, born 7 June 1952, took the IRAs' 2025 RMD on 18 March 2026, before 1 April 2026.
    assert "HH-0637" not in key.found
    (household,) = [h for h in key.households if h.household_id == "HH-0637"]
    assert all(r.met for r in household.requirements)


def test_the_key_writes_as_json(key: RmdSweepKey) -> None:
    data = key.to_dict()
    assert data["found"]["HH-5271"] == ["P-5271-1", "SYN-52710004"]
    assert {m["household_id"] for m in data["missed"]} == set(MISSED)
    json.dumps(data)


@pytest.fixture(scope="module")
def workspace(full_book: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("book")
    load_task_fixtures(full_book, "book", ("custodian", "portfolio", "crm"), date(2026, 4, 15), root)
    return root


def _output(households: list[dict[str, Any]], finding: str = "found") -> str:
    answer = {
        "finding": finding,
        "households": households,
        "unresolved": [],
        "figures": [
            {
                "label": "HH-5271 401(k) RMD",
                "value": "12729.96",
                "source": "households/HH-5271/custodian/positions.csv",
                "computed": True,
            }
        ],
        "explanation": "Five 401(k)s paid nothing in a first distribution year; five inherited IRAs paid nothing.",
    }
    return f"```json\n{json.dumps(answer, indent=2)}\n```\n"


ENTRIES = [
    {"household_id": h, "owner_id": owner, "account_ids": [account], "explanation": "Nothing taken."}
    for h, (owner, account) in MISSED.items()
]


def test_a_correct_list_passes_the_list_grader(key: RmdSweepKey, workspace: Path) -> None:
    result = grade(_output(ENTRIES), key, workspace)
    assert (result.score, result.critical_fail) == (100, None)


def test_naming_the_twin_that_aggregated_its_iras_is_a_false_alarm(key: RmdSweepKey, workspace: Path) -> None:
    twin = {"household_id": "HH-5814", "owner_id": "P-5814-1", "account_ids": ["SYN-58140003"]}
    result = grade(_output([*ENTRIES, twin]), key, workspace)
    assert not result.passed
    assert result.counts["false_alarm"] == 1


def test_missing_the_inherited_iras_fails(key: RmdSweepKey, workspace: Path) -> None:
    result = grade(_output([e for e in ENTRIES if e["account_ids"][0][-4:] == "0004"]), key, workspace)
    assert not result.passed


def test_an_invented_shortfall_in_a_household_entry_is_a_fabricated_figure(key: RmdSweepKey, workspace: Path) -> None:
    """Reviewers A and B, slice 9 round 1: a correct list whose every shortfall is invented, as a bare JSON
    number, scored 100; each entry's amounts are now judged like any headline amount."""
    invented = [e | {"shortfall": 987654321} for e in ENTRIES]
    result = grade(_output(invented), key, workspace)
    assert result.score == 0
    assert result.critical_fail is not None and "987654321" in result.critical_fail
    # The true shortfalls, from the key, pass.
    shortfalls = {household: str(requirement.shortfall) for household, requirement in key.missed}
    true = [e | {"shortfall": shortfalls[str(e["household_id"])]} for e in ENTRIES]
    assert grade(_output(true), key, workspace).critical_fail is None
