"""The 2025 tax documents: one for each event or income line that calls for one and nothing else,
their figures as the event log has them, and the custodian's own record where it differs."""

import os
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from casebook.generate.background import generate_background
from casebook.generate.script import HouseholdScript, load_scripts
from casebook.generate.simulate import simulate
from casebook.model.events import (
    CharitableDistribution,
    Dividend,
    RequiredDistribution,
    RothConversion,
    Sell,
    Withdrawal,
)
from casebook.model.money import parse_decimal
from casebook.model.tax import long_term
from casebook.notice import NOTICE
from casebook.plant import plant
from casebook.plant.common import PlantContext
from casebook.published_text import pdf_pages_text
from casebook.replay import replay
from casebook.securities.market import Market, build_market
from casebook.securities.master import by_id, load_master
from casebook.sources.context import SNAPSHOT_DAYS, EmitContext
from casebook.sources.tax_documents import (
    COMPOSITE_1099,
    FORM_1099_R,
    FORM_SSA_1099,
    FORM_W2,
    covered,
    emit,
    index_entries,
    reached_early_age,
)

from .conftest import SCRIPTS, SEED

TAXABLE = ("joint_taxable", "individual_taxable")
RETIREMENT = ("traditional_ira", "401k", "inherited_ira")


def _context(script: HouseholdScript, market: Market, real_tickers: bool = False) -> EmitContext:
    """The context the build hands an emitter: the events as the custodian recorded them."""
    master = load_master()
    simulation = simulate(script, market)
    replayed = replay(simulation.events, SNAPSHOT_DAYS)
    planting = plant(
        PlantContext(script, simulation.events, replayed, simulation.quarters, market, by_id(master), real_tickers)
    )
    events, ledger = simulation.events, replayed
    if planting.custodian_events is not None:
        events, ledger = planting.custodian_events, replay(planting.custodian_events, SNAPSHOT_DAYS)
    return EmitContext(script, events, ledger, market, by_id(master), real_tickers)


@pytest.fixture(scope="module")
def market() -> Market:
    return build_market(load_master(), SEED)


@pytest.fixture(scope="module")
def contexts(market: Market) -> dict[str, EmitContext]:
    """Every household of the public book: the featured scripts and the 80 drawn in the background."""
    scripts = [*load_scripts(SCRIPTS), *generate_background(SEED, market, None)]
    return {s.household.household_id: _context(s, market) for s in scripts}


@pytest.fixture(scope="module")
def drawn(contexts: dict[str, EmitContext]) -> dict[str, dict[str, bytes]]:
    return {hid: emit(context) for hid, context in contexts.items()}


def _text(files: dict[str, bytes], name: str) -> str:
    return "\n".join(pdf_pages_text(files[f"documents/{name}"]))


def _box(text: str, label: str) -> Decimal:
    found = re.search(re.escape(label) + r": (-?)\$([\d,]+\.\d\d)", text)
    assert found is not None, f"no {label!r} in the document"
    return parse_decimal(found.group(1) + found.group(2).replace(",", ""))


def _in_2025(day: date) -> bool:
    return day.year == 2025


def documents_match_events(contexts: dict[str, EmitContext]) -> set[str]:
    """Every taxable account with 2025 dividends or sales has its composite 1099, every retirement
    account with a 2025 distribution, conversion or QCD its 1099-R, every wage line its W-2 and
    every Social Security line its SSA-1099, and nothing else. Returns the kinds seen."""
    kinds_seen: set[str] = set()
    for hid, context in contexts.items():
        hh = context.script.household
        kind = {a.account_id: a.account_type for a in hh.accounts}
        expected: set[tuple[str, str]] = set()
        for e in context.events:
            if not _in_2025(e.date):
                continue
            if isinstance(e, Dividend | Sell) and kind[e.account_id] in TAXABLE:
                expected.add((COMPOSITE_1099, e.account_id))
            distribution = RequiredDistribution | Withdrawal | CharitableDistribution | RothConversion
            if isinstance(e, distribution) and kind[e.account_id] in RETIREMENT:
                expected.add((FORM_1099_R, e.account_id))
        lines = {"wages": FORM_W2, "social_security": FORM_SSA_1099}
        income = [(lines[i.kind], i.person_id) for i in hh.income if i.year == 2025]
        entries = index_entries(context)
        found = {(e["kind"], e.get("account_id") or e["person_id"]) for e in entries}
        assert found == expected | set(income), hid
        # One W-2 per wage line and one SSA-1099 per Social Security line, even for one person.
        assert sorted((e["kind"], e["person_id"]) for e in entries if "person_id" in e) == sorted(income), hid
        kinds_seen |= {e["kind"] for e in entries}
    return kinds_seen


def test_the_documents_present_are_the_ones_the_events_and_income_call_for(contexts: dict[str, EmitContext]) -> None:
    assert documents_match_events(contexts) == {COMPOSITE_1099, FORM_1099_R, FORM_W2, FORM_SSA_1099}


PRIVATE_SCRIPTS = Path(os.environ.get("CASEBOOK_PRIVATE", "/nonexistent")) / "book" / "scripted"


@pytest.mark.skipif(not PRIVATE_SCRIPTS.is_dir(), reason="the held-out pairs live in $CASEBOOK_PRIVATE")
def test_the_held_out_households_documents_are_the_ones_their_events_call_for(market: Market) -> None:
    held_out = {s.household.household_id: _context(s, market) for s in load_scripts(PRIVATE_SCRIPTS)}
    assert len(held_out) == 4
    assert COMPOSITE_1099 in documents_match_events(held_out)


def test_each_documents_figure_read_back_from_its_pdf_equals_the_event_logs(
    contexts: dict[str, EmitContext], drawn: dict[str, dict[str, bytes]]
) -> None:
    """Composite: box 1a plus box 12 is every 2025 dividend the account was paid. 1099-R: box 1
    across the account's forms is what left it. W-2 box 1 and SSA-1099 box 5: the income line."""
    for hid, context in contexts.items():
        files, hh = drawn[hid], context.script.household
        entries = index_entries(context)
        assert sorted(files) == sorted(f"documents/{e['file']}" for e in entries), hid
        gross_by_account: dict[str, Decimal] = {}
        income: dict[str, list[tuple[str, Decimal]]] = {"wages": [], "social_security": []}
        for line in hh.income:
            if line.year == 2025:
                income[line.kind].append((line.person_id, line.amount))
        read_income: dict[str, list[tuple[str, Decimal]]] = {"wages": [], "social_security": []}
        for entry in entries:
            text = _text(files, entry["file"])
            assert NOTICE.split(".")[0].split()[0] in text, entry["file"]
            match entry["kind"]:
                case "form_1099_composite":
                    paid = sum(
                        (
                            e.amount
                            for e in context.events
                            if isinstance(e, Dividend) and e.account_id == entry["account_id"] and _in_2025(e.date)
                        ),
                        Decimal(0),
                    )
                    shown = _box(text, "Box 1a Total ordinary dividends") + _box(
                        text, "Box 12 Exempt-interest dividends"
                    )
                    assert shown == paid, entry["file"]
                case "form_1099_r":
                    account = entry["account_id"]
                    gross_by_account[account] = gross_by_account.get(account, Decimal(0)) + _box(
                        text, "Box 1 Gross distribution"
                    )
                case "form_w2":
                    read_income["wages"].append(
                        (entry["person_id"], _box(text, "Box 1 Wages, tips, other compensation"))
                    )
                case _:
                    read_income["social_security"].append(
                        (entry["person_id"], _box(text, "Box 5 Net benefits for 2025"))
                    )
        for account, shown in gross_by_account.items():
            left = Decimal(0)
            for e in context.events:
                if e.account_id != account or not _in_2025(e.date):
                    continue
                if isinstance(e, RothConversion):
                    left += e.amount
                elif isinstance(e, RequiredDistribution | Withdrawal | CharitableDistribution):
                    left -= e.amount
            assert shown == left, (hid, account)
        assert {k: sorted(v) for k, v in read_income.items()} == {k: sorted(v) for k, v in income.items()}, hid


def test_index_entries_date_every_document_by_its_issue(contexts: dict[str, EmitContext]) -> None:
    issued = {
        COMPOSITE_1099: "2026-02-17",
        FORM_1099_R: "2026-01-30",
        FORM_W2: "2026-01-30",
        FORM_SSA_1099: "2026-01-31",
    }
    for context in contexts.values():
        entries = index_entries(context)
        assert len({e["document_id"] for e in entries}) == len(entries)
        for entry in entries:
            assert entry["valuation_date"] == "2025-12-31"
            assert entry["known_as_of"] == issued[entry["kind"]]
            assert ("account_id" in entry) != ("person_id" in entry)


def _one(files: dict[str, bytes], fragment: str) -> str:
    names = [n for n in files if fragment in n]
    assert len(names) == 1, names
    return "\n".join(pdf_pages_text(files[names[0]]))


def test_a_qcd_the_custodian_coded_as_a_distribution_shows_as_one_on_its_1099_r(
    drawn: dict[str, dict[str, bytes]],
) -> None:
    """HH-6047: Bernard, 78, paid $12,000.00 from his IRA to a charity and took a $9,659.73 RMD with
    $965.97 withheld. The custodian coded both as ordinary distributions: one form, code 7,
    $12,000.00 + $9,659.73 = $21,659.73."""
    files = drawn["HH-6047"]
    forms = [n for n in files if "1099R" in n]
    assert forms == ["documents/SYN-60470002-1099R-7-2025.pdf"]
    text = _one(files, "SYN-60470002-1099R")
    assert _box(text, "Box 1 Gross distribution") == Decimal("21659.73")
    assert _box(text, "Box 2a Taxable amount") == Decimal("21659.73")
    assert _box(text, "Box 4 Federal income tax withheld") == Decimal("965.97")
    assert "Box 7 Distribution code(s): 7\n" in text + "\n"
    assert "Box 2b Taxable amount not determined: X" in text
    assert "Box 7 IRA/SEP/SIMPLE: X" in text
    assert _box(_one(files, "P-6047-1-SSA1099"), "Box 5 Net benefits for 2025") == Decimal("38460.00")


def test_a_qcd_the_custodian_recorded_as_one_has_its_own_1099_r_coded_y7(drawn: dict[str, dict[str, bytes]]) -> None:
    """HH-6590: Celestine's $15,000.00 QCD, coded as one, and her $9,882.45 RMD with $988.25
    withheld: codes Y and 7 make separate forms."""
    files = drawn["HH-6590"]
    qcd = _one(files, "SYN-65900002-1099R-Y7")
    assert _box(qcd, "Box 1 Gross distribution") == Decimal("15000.00")
    assert _box(qcd, "Box 4 Federal income tax withheld") == Decimal("0.00")
    rmd = _one(files, "SYN-65900002-1099R-7-")
    assert _box(rmd, "Box 1 Gross distribution") == Decimal("9882.45")
    assert _box(rmd, "Box 4 Federal income tax withheld") == Decimal("988.25")


def test_a_roth_conversion_before_59_and_a_half_is_code_2(drawn: dict[str, dict[str, bytes]]) -> None:
    """HH-1204: Luka, born 1984-11-19, converts $7,000.00 on 2025-02-13, aged 40."""
    text = _one(drawn["HH-1204"], "SYN-12040003-1099R-2-")
    assert _box(text, "Box 1 Gross distribution") == Decimal("7000.00")
    assert "Box 7 IRA/SEP/SIMPLE: X" in text
    assert "Luka Kovac" in text


def _sales(text: str, security: str) -> list[tuple[str, str, str, str, str]]:
    """The 1099-B lines for `security`: acquired, sold, cost basis, term, covered (a cell to a line)."""
    cell = r"\n(\S+)"
    money = r"\n\$[\d,.]+"
    pattern = re.escape(security) + cell + cell + money + r"\n(\$[\d,.]+)" + money + cell + cell
    return re.findall(pattern, text)


def test_the_1099_b_shows_the_custodians_zero_basis_on_released_rsu_shares(drawn: dict[str, dict[str, bytes]]) -> None:
    """HH-3058: the custodian booked every release at no cost; the December sale of 1,600 shares
    closes the February and May releases, 800 shares each, held under a year."""
    text = _one(drawn["HH-3058"], "SYN-30580002-1099-")
    assert _sales(text, "800 Bramwell Devices Group") == [
        ("2025-02-20", "2025-12-12", "$0.00", "Short-term", "Covered"),
        ("2025-05-20", "2025-12-12", "$0.00", "Short-term", "Covered"),
    ]
    assert "Short-term total: proceeds $437,776.00, cost basis $0.00" in text
    wages = _one(drawn["HH-3058"], "P-3058-1-W2")
    assert "Employer: Bramwell Devices Group" in wages
    assert _box(wages, "Box 1 Wages, tips, other compensation") == Decimal("1175944.00")
    assert _box(wages, "Box 5 Medicare wages and tips") == Decimal("1175944.00")


def test_the_twin_custodian_books_the_release_value_as_basis(drawn: dict[str, dict[str, bytes]]) -> None:
    """HH-3462: the same December sale; every released lot sold carries a basis."""
    text = _one(drawn["HH-3462"], "SYN-34620002-1099-")
    sales = [line for units in ("400", "200") for line in _sales(text, f"{units} Ellisar Search Holdings")]
    assert len(sales) == 3
    assert all(basis != "$0.00" for _, _, basis, _, _ in sales)


def test_an_employer_named_for_a_security_is_named_by_its_ticker_in_a_real_ticker_build(market: Market) -> None:
    script = next(s for s in load_scripts(SCRIPTS) if s.household.household_id == "HH-3058")
    master = by_id(load_master())
    ticker = master["SEC-0028"].real_ticker
    files = emit(_context(script, market, real_tickers=True))
    text = _one(files, "P-3058-1-W2")
    assert f"Employer: {ticker}" in text
    assert "Bramwell" not in "".join("\n".join(pdf_pages_text(data)) for data in files.values())


@pytest.mark.parametrize(
    ("acquired", "sold", "is_long"),
    [
        (date(2024, 3, 15), date(2025, 3, 15), False),  # the anniversary: one year, not more
        (date(2024, 3, 15), date(2025, 3, 16), True),
        # Rev. Rul. 66-7: bought on the last day of February, long-term from 1 March
        (date(2024, 2, 29), date(2025, 2, 28), False),
        (date(2024, 2, 29), date(2025, 3, 1), True),
    ],
)
def test_a_lot_is_long_term_when_held_more_than_one_year(acquired: date, sold: date, is_long: bool) -> None:
    assert long_term(acquired, sold) is is_long


def test_age_59_and_a_half_is_six_calendar_months_after_the_59th_birthday() -> None:
    assert not reached_early_age(date(1966, 8, 31), date(2026, 2, 27))
    assert reached_early_age(date(1966, 8, 31), date(2026, 2, 28))
    assert not reached_early_age(date(1966, 1, 10), date(2025, 7, 9))
    assert reached_early_age(date(1966, 1, 10), date(2025, 7, 10))


def test_a_fund_is_covered_from_2012_and_a_stock_from_2011() -> None:
    assert not covered("Larkspur Total Market Fund", date(2011, 6, 1))
    assert covered("Larkspur Total Market Fund", date(2012, 1, 1))
    assert covered("Bramwell Devices Group", date(2011, 1, 1))
    assert not covered("Bramwell Devices Group", date(2010, 12, 31))


def test_the_book_has_noncovered_lots_sold_in_2025(drawn: dict[str, dict[str, bytes]]) -> None:
    """Opening lots reach back to the 1990s, so some 2025 sales close lots the custodian reports as noncovered."""
    assert any(
        "Noncovered" in "\n".join(pdf_pages_text(data))
        for files in drawn.values()
        for name, data in files.items()
        if "-1099-" in name
    )
