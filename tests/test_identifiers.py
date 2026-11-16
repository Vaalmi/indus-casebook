"""Slice 4: identifiers use ranges that cannot be valid (docs/PLAN.md, Choices), or the build fails."""

import json
import re
import shutil
from pathlib import Path

import pytest

from casebook.build import BuildError, build_book
from casebook.model.identifiers import file_problems, text_problems

from .conftest import SCRIPTS, SEED


@pytest.mark.parametrize(
    "text",
    [
        "SSN 000-48-2101",  # area 000 is never issued
        "call 555-0142",
        "call (312) 555-0199",
        "call 312-555-0100",
        "adaeze.okaforlind@mail.example",
        # Our own IDs and dates have digits and hyphens but no identifier's shape.
        "2026-04-15 T-4821-0025 L-48210001-04 AGR-4821-3 P-4821-1 BG-4821-1 SYN-48210001",
        "1,326,969.27 and 4,605.18",
    ],
)
def test_identifiers_in_their_invalid_ranges_pass(text: str) -> None:
    assert text_problems(text) == []


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("SSN 123-45-6789", "social security number 123-45-6789 is outside area 000"),
        ("Tax ID: 123456789", "social security number 123456789 is outside area 000"),
        ("call 555-0200", "phone number 555-0200 is outside 555-0100 to 555-0199"),
        ("call 312-867-5309", "phone number 312-867-5309 is outside 555-0100 to 555-0199"),
        ("call 867-5309", "phone number 867-5309 is outside 555-0100 to 555-0199"),
        ("write to jane@gmail.com", "email address jane@gmail.com is not under .example"),
    ],
)
def test_a_valid_looking_identifier_is_a_problem(text: str, problem: str) -> None:
    assert text_problems(text) == [problem]


def test_an_account_number_without_the_prefix_is_a_problem() -> None:
    csv_data = b"account_id,amount\nSYN-48210001,1.00\n12345678,2.00\n"
    assert file_problems("custodian/cash.csv", csv_data, csv_data.decode()) == [
        "custodian/cash.csv: account number 12345678 is not SYN- and eight digits"
    ]
    json_data = b'{"billing_groups": [{"account_ids": ["SYN-48210001", "ACCT-1"]}]}'
    assert file_problems("portfolio/household.json", json_data, "") == [
        "portfolio/household.json: account number ACCT-1 is not SYN- and eight digits"
    ]


def scripts_with(tmp_path: Path, household: str, old: str, new: str) -> Path:
    scripts = tmp_path / "scripted"
    shutil.copytree(SCRIPTS, scripts)
    path = scripts / "archetype-10" / f"{household}.toml"
    text = path.read_text()
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new))
    return scripts


def test_a_planted_valid_looking_social_security_number_fails_the_build(tmp_path: Path) -> None:
    scripts = scripts_with(tmp_path, "HH-4821", 'tax_id = "000-48-2101"', 'tax_id = "123-45-6789"')
    problem = "crm/crm.json: social security number 123-45-6789 is outside area 000"
    with pytest.raises(BuildError, match=re.escape(problem)):
        build_book(SEED, tmp_path / "book", scripts)
    assert not (tmp_path / "book").exists()


def test_a_real_looking_phone_number_fails_the_real_ticker_build_too(tmp_path: Path) -> None:
    scripts = scripts_with(tmp_path, "HH-7350", 'phone = "555-0161"', 'phone = "773-555-2368"')
    with pytest.raises(BuildError, match="phone number 773-555-2368"):
        build_book(SEED, tmp_path / "real", scripts, real_tickers=True)


def test_an_email_outside_example_fails_the_build(tmp_path: Path) -> None:
    scripts = scripts_with(tmp_path, "HH-7350", "kenji.sato@mail.example", "kenji.sato@gmail.com")
    with pytest.raises(BuildError, match=re.escape("email address kenji.sato@gmail.com is not under .example")):
        build_book(SEED, tmp_path / "book", scripts)


@pytest.mark.parametrize(
    ("field", "value", "problem"),
    [
        # Reviewers A and B, slice 4 round 1: forms the prose scan did not look for.
        ("tax_id", "123456789", "tax_id 123456789 is not a social security number in area 000, as 000-00-0000"),
        ("tax_id", "000 48 2101", "tax_id 000 48 2101 is not a social security number in area 000, as 000-00-0000"),
        ("phone", "312.867.5309", "phone 312.867.5309 is not a phone number in 555-0100 to 555-0199"),
        ("phone", "3128675309", "phone 3128675309 is not a phone number in 555-0100 to 555-0199"),
        ("email", "kenji.sato@example.com", "email kenji.sato@example.com is not an email address under .example"),
    ],
)
def test_an_identifier_field_must_have_its_invalid_shape_whole(field: str, value: str, problem: str) -> None:
    data = json.dumps({"contacts": [{"person_id": "P-1", field: value}]}).encode()
    assert f"crm/crm.json: {problem}" in file_problems("crm/crm.json", data, "")


def test_a_ten_digit_phone_split_by_dots_or_spaces_is_found_in_prose() -> None:
    assert text_problems("call 312.867.5309 or 312 867 5309") == [
        "phone number 312.867.5309 is outside 555-0100 to 555-0199",
        "phone number 312 867 5309 is outside 555-0100 to 555-0199",
    ]
    # A decimal amount is not a phone number.
    assert text_problems("0.4480 per unit, 277.05, 1,326,969.27") == []


def test_a_bare_nine_digit_tax_id_fails_the_build(tmp_path: Path) -> None:
    scripts = scripts_with(tmp_path, "HH-7350", 'tax_id = "000-73-5001"', 'tax_id = "123456789"')
    with pytest.raises(BuildError, match="tax_id 123456789 is not a social security number"):
        build_book(SEED, tmp_path / "book", scripts)


def test_a_split_phone_number_at_the_end_of_a_sentence_is_found() -> None:
    # Reviewer B, slice 4 round 2: a full stop after the number hid it.
    assert text_problems("Call 312.867.5309. Or 312 867 5309.") == [
        "phone number 312.867.5309 is outside 555-0100 to 555-0199",
        "phone number 312 867 5309 is outside 555-0100 to 555-0199",
    ]


def test_a_phone_number_in_an_agreement_summary_fails_the_build(tmp_path: Path) -> None:
    old = 'summary = "Householding letter: the joint account'
    scripts = scripts_with(
        tmp_path, "HH-4821", old, 'summary = "Call 312.867.5309. Householding letter: the joint account'
    )
    with pytest.raises(BuildError, match=re.escape("phone number 312.867.5309 is outside 555-0100 to 555-0199")):
        build_book(SEED, tmp_path / "book", scripts)
