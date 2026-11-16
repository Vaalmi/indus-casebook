from decimal import Decimal
from typing import Any

import pytest

from casebook.rules import RulesError, load_rules, parse_rules

D = Decimal

# Every name slice 5's planters read. A rename or a dropped row fails here first.
PARAMETER_NAMES = {
    "rmd_age",
    # The ages and gaps the RMD planters read (slice 7 moved them out of the planters' code).
    "rmd_age_before_secure",
    "rmd_age_secure",
    "rmd_age_from_1960",
    "joint_table_spouse_years",
    "qcd_age",
    "eligible_beneficiary_years",
    "age_of_majority",
    "niit_rate",
    "niit_threshold_mfj",
    "niit_threshold_mfs",
    "niit_threshold_single",
    "niit_threshold_hoh",
    "qcd_limit",
    "ira_contribution_limit",
    "ira_catch_up",
    "salt_cap",
    "salt_separate_share",
    "salt_phase_down_threshold",
    "salt_phase_down_threshold_mfs",
    "salt_phase_down_rate",
    "salt_floor",
    "capital_loss_limit",
    "capital_loss_limit_mfs",
    "wash_sale_days",
    "inherited_ira_years",
    "annual_rmd_enforced_from",
}

# Every name slice 7's tax calculators read.
TAX_PARAMETER_NAMES = {
    "standard_deduction_single",
    "standard_deduction_mfj",
    "standard_deduction_mfs",
    "standard_deduction_hoh",
    "additional_standard_deduction_married",
    "additional_standard_deduction_unmarried",
    "senior_deduction",
    "senior_deduction_phaseout_single",
    "senior_deduction_phaseout_joint",
    "senior_deduction_phaseout_rate",
    *(f"capital_gain_{band}_ceiling_{status}" for band in ("0", "15") for status in ("single", "mfj", "mfs", "hoh")),
    "capital_gain_rate_15",
    "capital_gain_rate_20",
    "additional_medicare_rate",
    *(f"additional_medicare_threshold_{status}" for status in ("single", "mfj", "mfs", "hoh")),
    "social_security_base_single",
    "social_security_base_mfj",
    "social_security_adjusted_base_single",
    "social_security_adjusted_base_mfj",
    *(f"amt_exemption_{status}" for status in ("single", "mfj", "mfs", "hoh")),
    *(f"amt_phaseout_{status}" for status in ("single", "mfj", "mfs", "hoh")),
    "amt_phaseout_rate",
    "amt_rate_break",
    "amt_rate_break_mfs",
    "amt_rate_low",
    "amt_rate_high",
}

BRACKET_TABLES = {"brackets_single", "brackets_mfj", "brackets_mfs", "brackets_hoh"}


def raw_rules(**parameter: Any) -> dict[str, Any]:
    return {
        "year": 2025,
        "parameters": {"niit_rate": parameter},
        "tables": {"uniform_lifetime": {"citation": "Pub. 590-B, Table III", "values": {"73": "26.5"}}},
    }


def test_the_2025_table_loads_with_a_citation_on_everything() -> None:
    rules = load_rules(2025)
    assert rules.year == 2025
    assert set(rules.parameters) == PARAMETER_NAMES | TAX_PARAMETER_NAMES
    assert set(rules.tables) == {"single_life", "uniform_lifetime"} | BRACKET_TABLES
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
        ("salt_separate_share", "0.5"),
        ("salt_phase_down_threshold", "500000"),
        ("salt_phase_down_rate", "0.30"),
        ("salt_floor", "10000"),
        ("capital_loss_limit_mfs", "1500"),
        ("rmd_age", "73"),
        # 26 U.S.C. 63(c)(2) and (c)(7) as amended by Pub. L. 119-21 § 70102.
        ("standard_deduction_single", "15750"),
        ("standard_deduction_mfj", "31500"),
        ("standard_deduction_mfs", "15750"),
        ("standard_deduction_hoh", "23625"),
        # Rev. Proc. 2024-40 § 3.15(3).
        ("additional_standard_deduction_married", "1600"),
        ("additional_standard_deduction_unmarried", "2000"),
        # 26 U.S.C. 151(d)(5)(C), added by Pub. L. 119-21 § 70103.
        ("senior_deduction", "6000"),
        ("senior_deduction_phaseout_single", "75000"),
        ("senior_deduction_phaseout_joint", "150000"),
        ("senior_deduction_phaseout_rate", "0.06"),
        # Rev. Proc. 2024-40 § 3.03.
        ("capital_gain_0_ceiling_mfj", "96700"),
        ("capital_gain_0_ceiling_single", "48350"),
        ("capital_gain_0_ceiling_hoh", "64750"),
        ("capital_gain_15_ceiling_mfj", "600050"),
        ("capital_gain_15_ceiling_single", "533400"),
        ("capital_gain_15_ceiling_mfs", "300000"),
        ("capital_gain_15_ceiling_hoh", "566700"),
        # 26 U.S.C. 3101(b)(2).
        ("additional_medicare_rate", "0.009"),
        ("additional_medicare_threshold_mfj", "250000"),
        ("additional_medicare_threshold_mfs", "125000"),
        # 26 U.S.C. 86(c).
        ("social_security_base_mfj", "32000"),
        ("social_security_adjusted_base_single", "34000"),
        # Rev. Proc. 2024-40 § 3.11.
        ("amt_exemption_mfj", "137000"),
        ("amt_exemption_single", "88100"),
        ("amt_exemption_mfs", "68500"),
        ("amt_phaseout_mfj", "1252700"),
        ("amt_phaseout_single", "626350"),
        ("amt_rate_break", "239100"),
        ("amt_rate_break_mfs", "119550"),
        ("amt_phaseout_rate", "0.25"),
        # 26 U.S.C. 401(a)(9)(C) as amended by the SECURE Acts; 408(d)(8)(B)(ii); 401(a)(9)(E)(ii)(V);
        # 26 CFR 1.401(a)(9)-5(c)(2) and -4(e)(3).
        ("rmd_age_before_secure", "70.5"),
        ("rmd_age_secure", "72"),
        ("rmd_age_from_1960", "75"),
        ("qcd_age", "70.5"),
        ("joint_table_spouse_years", "10"),
        ("eligible_beneficiary_years", "10"),
        ("age_of_majority", "21"),
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


@pytest.mark.parametrize(
    ("table", "rate", "start"),
    [
        # Rev. Proc. 2024-40 § 3.01, Tables 1 to 4.
        ("brackets_single", 1000, "0"),
        ("brackets_single", 1200, "11925"),
        ("brackets_single", 2400, "103350"),
        ("brackets_single", 3700, "626350"),
        ("brackets_mfj", 2200, "96950"),
        ("brackets_mfj", 3200, "394600"),
        ("brackets_mfj", 3700, "751600"),
        ("brackets_mfs", 3700, "375800"),
        ("brackets_hoh", 1200, "17000"),
        ("brackets_hoh", 3500, "250500"),
    ],
)
def test_verified_bracket_starts(table: str, rate: int, start: str) -> None:
    assert load_rules().factor(table, rate) == D(start)


@pytest.mark.parametrize("table", sorted(BRACKET_TABLES))
def test_every_bracket_table_has_the_seven_rates_rising(table: str) -> None:
    values = load_rules().tables[table].values
    assert sorted(values) == [1000, 1200, 2200, 2400, 3200, 3500, 3700]
    starts = [values[rate] for rate in sorted(values)]
    assert starts[0] == 0
    assert starts == sorted(starts)
    assert len(set(starts)) == 7


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
