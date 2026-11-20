import json
import re
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path

import pytest

from casebook.published_text import text_of
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


# A provider signature from a committed transcript, whose base64 holds "/Csco/" (published/runs/T-REC-06, line 165).
SIGNATURE = "w7kkdYs3IWxE1sE5oIAIlVEta+T9W+5EDugH7Rew/Csco/eXKXqm2lijdYKC16NYPkd6a8uHrvk0ianKZGarcQ"


def transcript_line(block: Mapping[str, object]) -> bytes:
    return json.dumps({"type": "assistant", "message": {"content": [block]}}).encode()


def test_a_provider_signature_is_left_out_of_the_scan_by_where_it_sits() -> None:
    scan = default_scan()
    block = {"type": "thinking", "thinking": "Reconcile the fees.", "signature": SIGNATURE}
    assert scan.find(text_of("run.transcript.jsonl", transcript_line(block))) == []
    # Escaped slashes, as some JSON writers write them, are the same signature.
    escaped = transcript_line(block).replace(b"/", b"\\/")
    assert scan.find(text_of("run.transcript.jsonl", escaped)) == []


@pytest.mark.parametrize(
    "block",
    [
        # The same characters anywhere but a thinking block's signature are text, and scanned.
        {"type": "thinking", "thinking": SIGNATURE, "signature": "x" * 64},
        {"type": "text", "text": SIGNATURE},
        {"type": "thinking", "thinking": "", "signature": SIGNATURE, "note": "a block of another shape"},
        {"type": "tool_use", "signature": SIGNATURE},
        # A signature that is not base64 is not one: it is scanned as text.
        {"type": "thinking", "thinking": "", "signature": "Trim Csco and msft, " + "x" * 64},
    ],
)
def test_the_same_characters_anywhere_else_are_scanned(block: dict[str, object]) -> None:
    found = {h.identifier for h in default_scan().find(text_of("run.transcript.jsonl", transcript_line(block)))}
    assert "Csco" in found


@pytest.mark.parametrize(
    "written",
    [
        # Gemini 4 Neon, asked by the owner after the whole-branch review: a guess from the characters took
        # these for base64, since one piece mixes digits with both cases.
        "/reports/Portfolio2026Review/msft/aapl/nvda",
        "https://docs.example.com/files/Ab3dEf7gHj9kLm2nPq/msft/aapl/summary",
        "plan=Portfolio2026Target+msft+aapl+nvda+csco",
        # And the base64 itself, outside a provider signature.
        SIGNATURE,
    ],
)
def test_a_ticker_beside_anything_that_looks_encoded_still_counts(written: str) -> None:
    found = {h.identifier.upper() for h in default_scan().find(written)}
    assert found >= ({"CSCO"} if written == SIGNATURE else {"MSFT", "AAPL"}), found


@pytest.mark.parametrize(
    "listed",
    [
        # The whole-branch review's targeted check: a list of tickers as long as base64 is still a list.
        "Compare Msft/Aapl/Csco/Nvda/Amzn/Googl/Avgo/Qcom/Jnj holdings.",
        "Security tickers: vti/vxus/bnd/msft/jnj/vea/vwo/vteb/vnq/vym",
        "Vti/Vxus/Bnd/Msft/Jnj/Vea/Vwo/Vteb/Vnq/Vym/2025",
    ],
)
def test_a_long_list_of_tickers_is_not_taken_for_base64(listed: str) -> None:
    found = default_scan().find(listed)
    assert len(found) == listed.count("/") + 1 - listed.count("/2025"), found
