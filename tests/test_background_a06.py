"""Slice 6: archetype 6's background pairs (a QCD toward an established RMD), drawn from the seed."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from casebook.build import build_book
from casebook.checks import check_book
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
    read_cash,
    read_csv,
    read_json,
    read_positions,
    read_transactions,
)
from casebook.model.money import cents
from casebook.securities.market import Market, build_market
from casebook.securities.master import load_master

from .conftest import SCRIPTS, SEED

ARCHETYPE = 6
# Pair 4 is a private pair, drawn only with the private salt: the public book holds pairs 2, 3 and 5.
PUBLIC_PAIRS = (2, 3, 5)
# The Uniform Lifetime factors for the ages archetype 6 draws, 74 to 87 (IRS Publication 590-B
# (2025), Appendix B, Table III).
UNIFORM_LIFETIME = {
    74: Decimal("25.5"),
    75: Decimal("24.6"),
    76: Decimal("23.7"),
    77: Decimal("22.9"),
    78: Decimal("22.0"),
    79: Decimal("21.1"),
    80: Decimal("20.2"),
    81: Decimal("19.4"),
    82: Decimal("18.5"),
    83: Decimal("17.7"),
    84: Decimal("16.8"),
    85: Decimal("16.0"),
    86: Decimal("15.2"),
    87: Decimal("14.4"),
}


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
    return {
        pair: draw_pair(SEED, ARCHETYPE, pair, *ids, market)
        for pair, ids in pair_ids(ARCHETYPE).items()
        if pair in PUBLIC_PAIRS
    }


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("background-a06") / "book"
    build_book(SEED, out, tmp_path_factory.mktemp("no-scripts"), background=True, background_archetypes=frozenset({6}))
    return out


def names(script: HouseholdScript) -> set[str]:
    return {p.name for p in script.household.members}


def balances(script: HouseholdScript, market: Market) -> set[Decimal]:
    return {opening_balance(a, market) for a in script.accounts}


def test_the_build_draws_six_public_households_and_every_check_passes(built: Path) -> None:
    sealed = json.loads((built / "sealed" / "households.json").read_text())["households"]
    assert sorted((h["archetype"], h["pair"], h["role"], h["set"]) for h in sealed) == sorted(
        (ARCHETYPE, pair, role, "background") for pair in PUBLIC_PAIRS for role in ("trap", "twin")
    )
    assert {h["twin_kind"] for h in sealed if h["role"] == "twin"} == {"clean"}
    report = check_book(built)
    assert len(report.lines) == 6 * 9
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


def test_the_qcd_and_the_later_distribution_pay_exactly_the_rmd(built: Path) -> None:
    sealed = json.loads((built / "sealed" / "households.json").read_text())["households"]
    for household in sealed:
        root = built / "households" / household["household_id"]
        (ira,) = [
            r["account_id"]
            for r in read_csv(root, ACCOUNTS_CSV, ACCOUNTS_COLUMNS)
            if r["account_type"] == "traditional_ira"
        ]
        members = read_json(root, PORTFOLIO_HOUSEHOLD)["household_membership"]
        born = date.fromisoformat(next(m["born"] for m in members if m["relationship"] == "primary"))
        balance = prior_year_end_balance(root, ira)
        rmd = cents(balance / UNIFORM_LIFETIME[2025 - born.year])
        paid = [t for t in read_transactions(root) if t.account_id == ira and t.type in (DISTRIBUTION, QCD)]
        assert -sum((t.amount for t in paid), Decimal(0)) == rmd
        # The trap's custodian recorded the QCD as an ordinary distribution; the twin's as a QCD.
        assert sorted(t.type for t in paid) == (
            [DISTRIBUTION, DISTRIBUTION] if household["role"] == "trap" else [DISTRIBUTION, QCD]
        )
