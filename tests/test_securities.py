import re

import pytest

from casebook.securities.master import MASTER_FIELDS, MasterFormatError, load_master, parse_master
from casebook.securities.scan import PRODUCT_ACRONYMS, default_scan


def test_every_security_has_exactly_the_three_fields() -> None:
    master = load_master()
    assert master
    assert all(set(vars(s)) == set(MASTER_FIELDS) for s in master)


def test_the_master_schema_rejects_a_fourth_field() -> None:
    entry = {"internal_id": "SEC-9", "alias": "Test Fund", "real_ticker": "ZZZQ", "cusip": "000000000"}
    with pytest.raises(MasterFormatError, match="exactly the fields"):
        parse_master([entry])


def test_ids_aliases_and_tickers_do_not_repeat() -> None:
    twice = [{"internal_id": f"SEC-{i}", "alias": f"Fund {i}", "real_ticker": "ZZZQ"} for i in (1, 2)]
    with pytest.raises(MasterFormatError, match="real_ticker values repeat"):
        parse_master(twice)


def test_real_tickers_are_scannable() -> None:
    for security in load_master():
        assert re.fullmatch(r"[A-Z]{3,5}", security.real_ticker), security
        assert security.real_ticker not in PRODUCT_ACRONYMS, security


def test_no_alias_contains_a_real_ticker_or_name() -> None:
    scan = default_scan()
    assert [s.alias for s in load_master() if scan.find(s.alias)] == []
