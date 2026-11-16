"""Slice 6: archetype 5's background pairs (a first RMD across two IRAs and a 401(k)), drawn from the seed."""

import json
from collections import defaultdict
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
    read_cash,
    read_csv,
    read_positions,
    read_transactions,
)
from casebook.model.money import cents
from casebook.securities.market import Market, build_market
from casebook.securities.master import load_master

from .conftest import SCRIPTS, SEED

ARCHETYPE = 5
# The Uniform Lifetime factor at age 73 (IRS Publication 590-B (2025), Appendix B, Table III).
FACTOR_AT_73 = Decimal("26.5")


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
    out = tmp_path_factory.mktemp("background-a05") / "book"
    build_book(SEED, out, tmp_path_factory.mktemp("no-scripts"), background=True, background_archetypes=frozenset({5}))
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


def test_the_pairs_differ_from_each_other_and_from_the_featured_pair(
    drawn: dict[int, tuple[HouseholdScript, HouseholdScript]], market: Market
) -> None:
    featured = load_scripts(SCRIPTS / f"archetype-{ARCHETYPE}")
    assert len(featured) == 2
    featured_names = set().union(*(names(s) for s in featured))
    featured_balances = set().union(*(balances(s, market) for s in featured))
    seen_names: set[str] = set()
    seen_balances: set[Decimal] = set()
    for trap, twin in drawn.values():
        pair_names = names(trap) | names(twin)
        pair_balances = balances(trap, market) | balances(twin, market)
        assert not pair_names & featured_names and not pair_balances & featured_balances
        assert not pair_names & seen_names and not pair_balances & seen_balances
        seen_names |= pair_names
        seen_balances |= pair_balances


def test_the_trap_pays_every_account_s_rmd_from_one_ira(built: Path) -> None:
    sealed = json.loads((built / "sealed" / "households.json").read_text())["households"]
    traps = [h["household_id"] for h in sealed if h["role"] == "trap"]
    assert len(traps) == 4
    for household_id in traps:
        root = built / "households" / household_id
        balance: dict[str, Decimal] = defaultdict(Decimal)
        for row in read_positions(root):
            if row.valuation_date == PRIOR_YEAR_END:
                balance[row.account_id] += row.market_value
        for row in read_cash(root):
            if row.valuation_date == PRIOR_YEAR_END:
                balance[row.account_id] += row.settled_cash + row.unsettled_cash
        types = {r["account_id"]: r["account_type"] for r in read_csv(root, ACCOUNTS_CSV, ACCOUNTS_COLUMNS)}
        rmds = {a: cents(balance[a] / FACTOR_AT_73) for a, kind in types.items() if kind in ("traditional_ira", "401k")}
        assert len(rmds) == 3
        paid = [t for t in read_transactions(root) if t.type == DISTRIBUTION]
        assert len(paid) == 1 and types[paid[0].account_id] == "traditional_ira"
        assert -paid[0].amount == sum(rmds.values())
        plan = next(a for a, kind in types.items() if kind == "401k")
        (entry,) = registry_entries(root)
        assert dict(entry.figures)["2025 RMD, 401(k)"] == f"${rmds[plan]:,.2f}"
