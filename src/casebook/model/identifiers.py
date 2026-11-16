"""Identifiers that cannot be valid (docs/PLAN.md, Choices; docs/SPEC.md, "Real personal data in the book").

Social security numbers sit in area 000, which is never issued; phone numbers in 555-0100 to
555-0199, which are reserved for fiction; email addresses under `.example`; account numbers
start `SYN-`. A number of any of these kinds in another shape fails the build.
"""

import csv
import io
import json
import re
from collections.abc import Iterator
from typing import Any, cast

# Three-two-four digits, the shape of a social security number, wherever it appears.
_SSN = re.compile(r"(?<![\w-])(\d{3})-(\d{2})-(\d{4})(?![\w-])")
# Nine digits named as a social security or taxpayer number.
_SSN_UNBROKEN = re.compile(r"(?i)(?:\bssn|\bsocial security(?: number)?|\btin|\btax[ _]id)\W{0,3}(\d{9})(?!\d)")
# A seven-digit phone number, with or without a three-digit area code before it; or ten digits
# split by dots or spaces. (Seven digits split by a dot read as a decimal number, so they are not one.)
_PHONE = re.compile(r"(?<![\w.-])(?:\(\d{3}\) ?|\d{3}[-. ])?(\d{3})-(\d{4})(?![\w-])")
# A full stop may end the sentence after one; a dot or hyphen followed by a digit continues the number.
_PHONE_SPLIT = re.compile(r"(?<![\w.-])\(?\d{3}\)?[. ](\d{3})[. ](\d{4})(?!\w|[.-]\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*)")
_ACCOUNT = re.compile(r"SYN-\d{8}")
ACCOUNT_FIELDS = ("account_id", "account_ids")
# The whole value of an identifier field must have its invalid shape; the prose scan alone would
# miss a number written in a form it does not look for.
FIELD_SHAPES = {
    "tax_id": (re.compile(r"000-\d{2}-\d{4}"), "a social security number in area 000, as 000-00-0000"),
    "phone": (re.compile(r"(?:\(\d{3}\) |\d{3}-)?555-01\d\d"), "a phone number in 555-0100 to 555-0199"),
    "email": (re.compile(r"[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)*example"), "an email address under .example"),
}
NEVER_ISSUED_AREA = "000"
FICTIONAL_EXCHANGE = "555"
FICTIONAL_LINES = range(100, 200)
EMAIL_DOMAIN = ".example"


def text_problems(text: str) -> list[str]:
    """Every social security number, phone number and email address in `text` not in its invalid range."""
    problems: list[str] = []
    for match in _SSN.finditer(text):
        if match.group(1) != NEVER_ISSUED_AREA:
            problems.append(f"social security number {match.group(0)} is outside area {NEVER_ISSUED_AREA}")
    for match in _SSN_UNBROKEN.finditer(text):
        if not match.group(1).startswith(NEVER_ISSUED_AREA):
            problems.append(f"social security number {match.group(1)} is outside area {NEVER_ISSUED_AREA}")
    for pattern in (_PHONE, _PHONE_SPLIT):
        for match in pattern.finditer(text):
            exchange, line = match.group(1), int(match.group(2))
            if exchange != FICTIONAL_EXCHANGE or line not in FICTIONAL_LINES:
                problems.append(f"phone number {match.group(0)} is outside 555-0100 to 555-0199")
    for match in _EMAIL.finditer(text):
        if not match.group(1).lower().endswith(EMAIL_DOMAIN):
            problems.append(f"email address {match.group(0)} is not under {EMAIL_DOMAIN}")
    return problems


def _json_fields(data: Any) -> Iterator[tuple[str, str]]:
    if isinstance(data, dict):
        for key, value in cast(dict[str, Any], data).items():
            if isinstance(value, dict | list):
                if key in ACCOUNT_FIELDS and isinstance(value, list):
                    yield from ((key, str(v)) for v in cast(list[Any], value))
                else:
                    yield from _json_fields(value)
            elif value is not None:
                yield key, str(value)
    elif isinstance(data, list):
        for item in cast(list[Any], data):
            yield from _json_fields(item)


def _fields(name: str, data: bytes) -> Iterator[tuple[str, str]]:
    """Every (field, value) a CSV column or a JSON key gives."""
    if name.endswith(".csv"):
        for row in csv.DictReader(io.StringIO(data.decode("utf-8"))):
            yield from ((k, v) for k, v in row.items() if v)
    elif name.endswith(".json"):
        yield from _json_fields(json.loads(data))


def file_problems(name: str, data: bytes, text: str) -> list[str]:
    """`text_problems` on a file's text (a PDF's included), plus every identifier field a CSV column
    or JSON key gives whose whole value lacks its invalid shape."""
    problems = text_problems(text)
    for field, value in _fields(name, data):
        if field in ACCOUNT_FIELDS and not _ACCOUNT.fullmatch(value):
            problems.append(f"account number {value} is not SYN- and eight digits")
        elif field in FIELD_SHAPES and not FIELD_SHAPES[field][0].fullmatch(value):
            problems.append(f"{field} {value} is not {FIELD_SHAPES[field][1]}")
    return [f"{name}: {p}" for p in dict.fromkeys(problems)]
