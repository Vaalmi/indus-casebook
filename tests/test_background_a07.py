"""Slice 6: archetype 7's background pairs (an inherited IRA under the ten-year rule), drawn from the seed.

These pairs are public background households; only archetype 7's featured pair is held out, so the
comparison with it runs only where $CASEBOOK_PRIVATE holds it."""

import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from casebook.build import build_book
from casebook.checks import check_book
from casebook.checks.book import registry_entries
from casebook.generate.background import BACKGROUND_PAIRS, background_ids, draw_pair
from casebook.generate.background.a05_first_rmd import opening_balance
from casebook.generate.script import HouseholdScript, load_scripts
from casebook.model.archetypes import ARCHETYPES
from casebook.model.dates import PRIOR_YEAR_END
from casebook.model.files import (
    ACCOUNTS_COLUMNS,
    ACCOUNTS_CSV,
    DISTRIBUTION,
    PORTFOLIO_HOUSEHOLD,
    QCD,
    WITHDRAWAL,
    read_cash,
    read_csv,
    read_json,
    read_positions,
    read_transactions,
)
from casebook.model.money import cents
from casebook.securities.market import Market, build_market
from casebook.securities.master import load_master

from .conftest import SEED

ARCHETYPE = 7
PRIVATE_PAIR = Path(os.environ.get("CASEBOOK_PRIVATE", "/nonexistent")) / "book" / "scripted" / "archetype-7"
# The Single Life Expectancy factors at the heirs' ages in the year after the death, for the traps
# seed 2026 draws (IRS Publication 590-B (2025), Appendix B, Table I).
SINGLE_LIFE = {40: Decimal("45.7"), 52: Decimal("34.3"), 54: Decimal("32.5"), 64: Decimal("23.7")}


def pair_ids(archetype: int) -> dict[int, tuple[str, str]]:
    """Each background pair's trap and twin IDs, where the full draw puts them."""
    ids = iter(background_ids(SEED))
    found: dict[int, tuple[str, str]] = {}
    for a in sorted(ARCHETYPES):
        for pair in BACKGROUND_PAIRS:
            trap, twin = next(ids), next(ids)
            if a == archetype:
                found[pair] = (trap, twin)
    return found


@pytest.fixture(scope="module")
def market() -> Market:
    return build_market(load_master(), SEED)


@pytest.fixture(scope="module")
def drawn(market: Market) -> dict[int, tuple[HouseholdScript, HouseholdScript]]:
    return {pair: draw_pair(SEED, ARCHETYPE, pair, *ids, market) for pair, ids in pair_ids(ARCHETYPE).items()}


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("background-a07") / "book"
    build_book(SEED, out, tmp_path_factory.mktemp("no-scripts"), background=True, background_archetypes=frozenset({7}))
    return out


def names(script: HouseholdScript) -> set[str]:
    return {p.name for p in script.household.members}


def balances(script: HouseholdScript, market: Market) -> set[Decimal]:
    return {opening_balance(a, market) for a in script.accounts}


def test_the_build_draws_eight_households_and_every_check_passes(built: Path) -> None:
    sealed = json.loads((built / "sealed" / "households.json").read_text())["households"]
    assert sorted((h["archetype"], h["pair"], h["role"], h["set"]) for h in sealed) == sorted(
        (ARCHETYPE, pair, role, "background") for pair in BACKGROUND_PAIRS for role in ("trap", "twin")
    )
    assert {h["twin_kind"] for h in sealed if h["role"] == "twin"} == {"near_miss"}
    report = check_book(built)
    assert len(report.lines) == 72
    assert [line for line in report.lines if not line.passed] == []


def test_the_same_pair_draws_the_same_households(market: Market) -> None:
    trap_id, twin_id = pair_ids(ARCHETYPE)[3]
    assert draw_pair(SEED, ARCHETYPE, 3, trap_id, twin_id, market) == draw_pair(
        SEED, ARCHETYPE, 3, trap_id, twin_id, market
    )


def test_the_pairs_differ_from_each_other(
    drawn: dict[int, tuple[HouseholdScript, HouseholdScript]], market: Market
) -> None:
    seen_names: set[str] = set()
    seen_balances: set[Decimal] = set()
    for trap, twin in drawn.values():
        pair_names = names(trap) | names(twin)
        pair_balances = balances(trap, market) | balances(twin, market)
        assert not pair_names & seen_names and not pair_balances & seen_balances
        seen_names |= pair_names
        seen_balances |= pair_balances


@pytest.mark.skipif(
    not PRIVATE_PAIR.is_dir(), reason="the held-out pair for archetype 7 lives in $CASEBOOK_PRIVATE, absent here"
)
def test_no_pair_shares_a_name_or_an_opening_balance_with_the_featured_pair(
    drawn: dict[int, tuple[HouseholdScript, HouseholdScript]], market: Market
) -> None:
    featured = load_scripts(PRIVATE_PAIR)
    assert len(featured) == 2
    featured_names = set().union(*(names(s) for s in featured))
    featured_names |= {a.inherited_from.name for s in featured for a in s.household.accounts if a.inherited_from}
    featured_balances = set().union(*(balances(s, market) for s in featured))
    for trap, twin in drawn.values():
        pair_names = names(trap) | names(twin)
        pair_names |= {a.inherited_from.name for s in (trap, twin) for a in s.household.accounts if a.inherited_from}
        assert not pair_names & featured_names
        assert not (balances(trap, market) | balances(twin, market)) & featured_balances


def prior_year_end_balance(root: Path, account_id: str) -> Decimal:
    """An account's 31 December 2024 balance read from positions.csv and cash.csv."""
    positions = (
        r.market_value
        for r in read_positions(root)
        if r.account_id == account_id and r.valuation_date == PRIOR_YEAR_END
    )
    cash = (
        r.settled_cash + r.unsettled_cash
        for r in read_cash(root)
        if r.account_id == account_id and r.valuation_date == PRIOR_YEAR_END
    )
    return sum(positions, Decimal(0)) + sum(cash, Decimal(0))


def test_the_trap_owes_an_annual_rmd_and_the_twin_none(built: Path) -> None:
    sealed = json.loads((built / "sealed" / "households.json").read_text())["households"]
    for household in sealed:
        root = built / "households" / household["household_id"]
        (account,) = [r for r in read_csv(root, ACCOUNTS_CSV, ACCOUNTS_COLUMNS) if r["account_type"] == "inherited_ira"]
        died, parent_born = date.fromisoformat(account["decedent_died"]), date.fromisoformat(account["decedent_born"])
        assert not [
            t
            for t in read_transactions(root)
            if t.account_id == account["account_id"] and t.amount < 0 and t.type in (DISTRIBUTION, QCD, WITHDRAWAL)
        ]
        if household["role"] == "twin":
            # Born 1951 to 1959, the parent's applicable age was 73, and the required beginning date
            # 1 April of the year after reaching it; the death came before it.
            assert 1951 <= parent_born.year <= 1959 and died < date(parent_born.year + 74, 4, 1)
            assert registry_entries(root) == []
            continue
        members = read_json(root, PORTFOLIO_HOUSEHOLD)["household_membership"]
        heir_born = date.fromisoformat(next(m["born"] for m in members if m["relationship"] == "primary"))
        first_year = died.year + 1
        period = SINGLE_LIFE[first_year - heir_born.year] - (2025 - first_year)
        (entry,) = registry_entries(root)
        figures = dict(entry.figures)
        assert figures["Distribution period"] == str(period)
        assert figures["2025 RMD"] == f"${cents(prior_year_end_balance(root, account['account_id']) / period):,.2f}"
        assert figures["Account to be emptied by"] == f"{died.year + 10}-12-31"
