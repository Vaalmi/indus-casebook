import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

from casebook.generate.script import ScriptError, load_scripts, parse_script
from casebook.model.events import UnsupportedEventError

from .conftest import FEATURED, SCRIPTS

TRAP = SCRIPTS / "archetype-10" / "HH-4821.toml"


def raw() -> dict[str, Any]:
    with TRAP.open("rb") as handle:
        return tomllib.load(handle)


def test_the_scripted_pairs_load() -> None:
    scripts = load_scripts(SCRIPTS)
    assert sorted(s.household.household_id for s in scripts) == list(FEATURED)
    assert [(s.household.household_id, s.role) for s in load_scripts(SCRIPTS / "archetype-10")] == [
        ("HH-4821", "trap"),
        ("HH-7350", "twin"),
    ]


def test_a_scripted_event_outside_the_whitelist_is_rejected_by_name() -> None:
    data = raw()
    data["activity"].append({"type": "merger", "date": "2025-06-01", "account_id": "SYN-48210001"})
    with pytest.raises(UnsupportedEventError, match="'merger'"):
        parse_script(data, "test.toml")


def test_a_trap_needs_its_planted_item() -> None:
    data = raw()
    del data["planted"]
    with pytest.raises(ScriptError, match="a trap has one planted item"):
        parse_script(data, "test.toml")


def test_every_account_is_in_one_billing_group() -> None:
    data = raw()
    data["billing_groups"][1]["account_ids"] = []
    with pytest.raises(ScriptError, match="exactly one billing group"):
        parse_script(data, "test.toml")


def test_activity_on_an_unknown_account_is_refused() -> None:
    data = raw()
    data["activity"][0]["account_id"] = "SYN-99999999"
    with pytest.raises(ScriptError, match="unknown account"):
        parse_script(data, "test.toml")


def test_a_malformed_script_names_its_file() -> None:
    data = raw()
    del data["members"]
    with pytest.raises(ScriptError, match=re.escape("test.toml")):
        parse_script(data, "test.toml")


def test_two_scripts_may_not_share_a_household_id(tmp_path: Path) -> None:
    for name in ("a.toml", "b.toml"):
        (tmp_path / name).write_bytes(TRAP.read_bytes())
    with pytest.raises(ScriptError, match="share a household ID"):
        load_scripts(tmp_path)


def test_beneficiaries_and_restrictions_load_typed() -> None:
    script = parse_script(raw(), "test.toml")
    first = script.household.beneficiaries[0]
    assert (first.account_id, first.designation, first.name, str(first.share), first.person_id) == (
        "SYN-48210002",
        "primary",
        "Adaeze Okafor-Lind",
        "100",
        "P-4821-1",
    )
    assert script.household.person("P-4821-1").tax_id == "000-48-2101"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"account_id": "SYN-99999999"}, "a beneficiary names unknown account SYN-99999999"),
        ({"designation": "secondary"}, "designation 'secondary' is not one of"),
        ({"person_id": "P-0000-1"}, "names P-0000-1, who is not in the household"),
        ({"share": "60"}, "SYN-48210002's primary beneficiaries share 60%, not 100%"),
    ],
)
def test_a_beneficiary_designation_that_cannot_hold_is_refused(change: dict[str, str], message: str) -> None:
    data = raw()
    data["beneficiaries"][0].update(change)
    with pytest.raises(ScriptError, match=re.escape(message)):
        parse_script(data, "test.toml")
