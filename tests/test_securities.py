import json
import re
from importlib.resources import files
from pathlib import Path

import pytest

from casebook.securities.master import MASTER_FIELDS, MasterFormatError, Security, load_master, parse_master
from casebook.securities.scan import PRODUCT_ACRONYMS, RealIdentifier, default_scan

ENGLISH_WORDS = Path(__file__).parent / "fixtures" / "english_words.txt"
REAL_NAMES = files("casebook.securities") / "real_names.json"


# Words web2 (1934) lacks that a modern dictionary holds, each found in review.
MODERN_WORDS = frozenset({"vig"})  # slang for vigorish (reviewer_a, slice 4 round 1)


def english_words() -> frozenset[str]:
    lines = ENGLISH_WORDS.read_text(encoding="utf-8").splitlines()
    return frozenset(line for line in lines if line and not line.startswith("#")) | MODERN_WORDS


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
    words = english_words()
    for security in load_master():
        assert re.fullmatch(r"[A-Z]{3,5}", security.real_ticker), security
        assert security.real_ticker not in PRODUCT_ACRONYMS, security
        assert security.real_ticker.lower() not in words, security


def test_no_alias_contains_a_real_ticker_or_name() -> None:
    scan = default_scan()
    assert [s.alias for s in load_master() if scan.find(s.alias)] == []


def test_the_master_lists_fifty_securities_in_id_order() -> None:
    expected = [f"SEC-{n:04d}" for n in range(1, 51)]
    assert [s.internal_id for s in load_master()] == expected


def test_the_first_five_securities_never_change() -> None:
    assert load_master()[:5] == (
        Security("SEC-0001", "Larkspur Total Market Fund", "VTI"),
        Security("SEC-0002", "Larkspur World ex-US Fund", "VXUS"),
        Security("SEC-0003", "Larkspur Core Bond Fund", "BND"),
        Security("SEC-0004", "Orrin Software Group", "MSFT"),
        Security("SEC-0005", "Halvern Health Holdings", "JNJ"),
    )


def test_the_word_list_knows_ordinary_words() -> None:
    assert {"cat", "low", "cost", "tip", "dis", "vig"} <= english_words()


def test_every_real_ticker_has_a_real_name_and_no_name_is_orphaned() -> None:
    names = json.loads(REAL_NAMES.read_text(encoding="utf-8"))["names"]
    tickers = {s.real_ticker for s in load_master()}
    assert [t for t in sorted(tickers) if not names.get(t)] == []
    assert sorted(set(names) - tickers) == []


def test_the_scan_finds_every_real_ticker_and_no_alias() -> None:
    scan = default_scan()
    for security in load_master():
        found = scan.find(f"bought 10 {security.real_ticker} today")
        assert found == [RealIdentifier(security.real_ticker, "ticker")], security
        assert scan.find(f"bought 10 {security.alias} today") == [], security


def test_the_scan_finds_a_real_ticker_written_in_any_case() -> None:
    """Whole-branch review, both reviewers: "Trim msft." and then "Trim Msft and AaPl." passed the scan."""
    scan = default_scan()
    for security in load_master():
        for written in (security.real_ticker.lower(), security.real_ticker.title(), security.real_ticker.swapcase()):
            assert scan.find(f"trim {written}.") == [RealIdentifier(written, "ticker")], (security, written)


def test_a_ticker_spelled_by_chance_inside_base64_is_not_one_but_upper_case_still_counts() -> None:
    """A committed transcript's base64 holds "/Csco/" (published/runs/T-REC-06, a basic run's line 165)."""
    blob = "w7kkdYs3IWxE1sE5oIAIlVEta+T9W+5EDugH7Rew/Csco/eXKXqm2lijdYKC16NYPkd6a8uHrvk0ianKZGarcQ"
    scan = default_scan()
    assert scan.find(blob) == []
    assert scan.find(blob.replace("/Csco/", "/CSCO/")) == [RealIdentifier("CSCO", "ticker")]
    # A short run is prose, not base64: "Csco/Msft" is two tickers.
    assert scan.find("trim Csco/Msft today") == [RealIdentifier("Csco", "ticker"), RealIdentifier("Msft", "ticker")]
