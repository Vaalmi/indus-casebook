from decimal import Decimal
from typing import Any

import pytest

from casebook.rules import RulesError, load_rules, parse_rules

D = Decimal

# Every name slice 5's planters read. A rename or a dropped row fails here first.
PARAMETER_NAMES = {
    "rmd_age",
    "niit_rate",
    "niit_threshold_mfj",
    "niit_threshold_mfs",
    "niit_threshold_single",
    "niit_threshold_hoh",
    "qcd_limit",
    "ira_contribution_limit",
    "ira_catch_up",
    "salt_cap",
    "salt_cap_mfs",
    "salt_phase_down_threshold",
    "salt_phase_down_threshold_mfs",
    "salt_phase_down_rate",
    "salt_floor",
    "salt_floor_mfs",
    "capital_loss_limit",
    "capital_loss_limit_mfs",
    "wash_sale_days",
    "inherited_ira_years",
    "annual_rmd_enforced_from",
}


def raw_rules(**parameter: Any) -> dict[str, Any]:
    return {
        "year": 2025,
        "parameters": {"niit_rate": parameter},
        "tables": {"uniform_lifetime": {"citation": "Pub. 590-B, Table III", "values": {"73": "26.5"}}},
    }


def test_the_2025_table_loads_with_a_citation_on_everything() -> None:
    rules = load_rules(2025)
    assert rules.year == 2025
    assert set(rules.parameters) == PARAMETER_NAMES
    assert set(rules.tables) == {"single_life", "uniform_lifetime"}
    for name in [*rules.parameters, *rules.tables]:
        assert rules.citation(name).strip()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        # 26 U.S.C. 1411(a)(1) and (b).
        ("niit_rate", "0.038"),
        ("niit_threshold_mfj", "250000"),
        ("niit_threshold_mfs", "125000"),
        ("niit_threshold_single", "200000"),
        ("niit_threshold_hoh", "200000"),
        # IRS Notice 2024-80.
        ("qcd_limit", "108000"),
        ("ira_contribution_limit", "7000"),
        ("ira_catch_up", "1000"),
        # 26 U.S.C. 164(b)(6)-(7) as amended by Pub. L. 119-21.
        ("salt_cap", "40000"),
        ("salt_cap_mfs", "20000"),
        ("salt_phase_down_threshold", "500000"),
        ("salt_phase_down_rate", "0.30"),
        ("salt_floor", "10000"),
        ("capital_loss_limit_mfs", "1500"),
        ("rmd_age", "73"),
    ],
)
def test_verified_parameter_values(name: str, value: str) -> None:
    assert load_rules().value(name) == D(value)


@pytest.mark.parametrize(
    ("table", "age", "factor"),
    [
        # IRS Pub. 590-B (2025), Appendix B, Table III.
        ("uniform_lifetime", 72, "27.4"),
        ("uniform_lifetime", 73, "26.5"),
        ("uniform_lifetime", 75, "24.6"),
        ("uniform_lifetime", 80, "20.2"),
        ("uniform_lifetime", 120, "2.0"),
        # Appendix B, Table I.
        ("single_life", 0, "84.6"),
        ("single_life", 50, "36.2"),
        ("single_life", 60, "27.1"),
        ("single_life", 75, "14.8"),
        ("single_life", 120, "1.0"),
    ],
)
def test_verified_table_factors(table: str, age: int, factor: str) -> None:
    assert load_rules().factor(table, age) == D(factor)


def test_the_tables_cover_every_age_they_are_used_for() -> None:
    rules = load_rules()
    assert set(rules.tables["single_life"].values) == set(range(121))
    assert set(rules.tables["uniform_lifetime"].values) == set(range(72, 121))


def test_a_parameter_with_no_citation_fails_to_load() -> None:
    with pytest.raises(RulesError, match=r"test\.toml: parameter 'niit_rate': no citation"):
        parse_rules(raw_rules(value="0.038"), "test.toml")


def test_a_parameter_with_an_empty_citation_fails_to_load() -> None:
    with pytest.raises(RulesError, match="parameter 'niit_rate': empty citation"):
        parse_rules(raw_rules(value="0.038", citation="  "), "test.toml")


def test_a_table_with_no_citation_fails_to_load() -> None:
    raw = raw_rules(value="0.038", citation="26 U.S.C. 1411(a)(1)")
    del raw["tables"]["uniform_lifetime"]["citation"]
    with pytest.raises(RulesError, match="table 'uniform_lifetime': no citation"):
        parse_rules(raw, "test.toml")


def test_a_parameter_with_no_value_fails_to_load() -> None:
    with pytest.raises(RulesError, match="parameter 'niit_rate': no value"):
        parse_rules(raw_rules(citation="26 U.S.C. 1411(a)(1)"), "test.toml")


@pytest.mark.parametrize("value", [0.038, 38])
def test_a_number_that_is_not_a_string_fails_to_load(value: Any) -> None:
    with pytest.raises(RulesError, match=f"parameter 'niit_rate': value must be a string.*{type(value).__name__}"):
        parse_rules(raw_rules(value=value, citation="26 U.S.C. 1411(a)(1)"), "test.toml")


def test_a_value_that_is_not_a_decimal_fails_to_load() -> None:
    with pytest.raises(RulesError, match=r"parameter 'niit_rate': not a decimal: '3\.8%'"):
        parse_rules(raw_rules(value="3.8%", citation="26 U.S.C. 1411(a)(1)"), "test.toml")


def test_an_unknown_parameter_is_named() -> None:
    with pytest.raises(RulesError, match="no parameter 'niit_rat' in the 2025 rules"):
        load_rules().value("niit_rat")


def test_an_unknown_citation_is_named() -> None:
    with pytest.raises(RulesError, match="no parameter or table 'joint_life' in the 2025 rules"):
        load_rules().citation("joint_life")


def test_an_absent_age_names_the_table_and_the_age() -> None:
    with pytest.raises(RulesError, match="table 'uniform_lifetime' in the 2025 rules has no entry for 71"):
        load_rules().factor("uniform_lifetime", 71)


def test_an_unknown_table_is_named() -> None:
    with pytest.raises(RulesError, match="no table 'joint_life' in the 2025 rules"):
        load_rules().factor("joint_life", 73)


def test_a_year_with_no_rules_file_fails() -> None:
    with pytest.raises(RulesError, match="no rules table for 1999"):
        load_rules(1999)
