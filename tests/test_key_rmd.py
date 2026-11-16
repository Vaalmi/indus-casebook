"""The RMD key against hand-worked households and the featured pair of archetype 5 in the built book."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.keys.rmd import UnsettledRmdError, household_rmd
from casebook.model.files import (
    ACCOUNTS_COLUMNS,
    ACCOUNTS_CSV,
    BENEFICIARIES_COLUMNS,
    BENEFICIARIES_CSV,
    CASH_COLUMNS,
    CASH_CSV,
    DOCUMENTS_INDEX,
    PORTFOLIO_HOUSEHOLD,
    POSITIONS_COLUMNS,
    POSITIONS_CSV,
    TRANSACTIONS_COLUMNS,
    TRANSACTIONS_CSV,
    csv_text,
    household_dir,
    json_text,
)

YEAR_END = "2024-12-31"


def _row(columns: tuple[str, ...], **values: str) -> dict[str, str]:
    row = dict.fromkeys(columns, "")
    row.update(values)
    return row


def account(account_id: str, kind: str, decedent: tuple[str, str] | None = None) -> dict[str, str]:
    born, died = decedent or ("", "")
    return _row(
        ACCOUNTS_COLUMNS,
        account_id=account_id,
        account_type=kind,
        decedent="A decedent" if decedent else "",
        decedent_born=born,
        decedent_died=died,
    )


def position(account_id: str, value: str, day: str = YEAR_END) -> dict[str, str]:
    return _row(
        POSITIONS_COLUMNS, account_id=account_id, units="1", price=value, market_value=value, valuation_date=day
    )


def cash(account_id: str, amount: str, day: str = YEAR_END) -> dict[str, str]:
    return _row(CASH_COLUMNS, account_id=account_id, settled_cash=amount, unsettled_cash="0.00", valuation_date=day)


def payout(transaction_id: str, account_id: str, day: str, kind: str, amount: str) -> dict[str, str]:
    return _row(
        TRANSACTIONS_COLUMNS,
        transaction_id=transaction_id,
        account_id=account_id,
        trade_date=day,
        settle_date=day,
        type=kind,
        amount=amount,
        description=kind,
    )


def spouse_beneficiary(account_id: str, person_id: str) -> dict[str, str]:
    return _row(
        BENEFICIARIES_COLUMNS,
        account_id=account_id,
        designation="primary",
        name="Spouse",
        relationship="spouse",
        share_percent="100",
        person_id=person_id,
    )


def write_household(
    root: Path,
    people: dict[str, str],
    accounts: list[tuple[dict[str, str], str]],
    positions: list[dict[str, str]],
    cash_rows: list[dict[str, str]],
    transactions: list[dict[str, str]],
    beneficiaries: list[dict[str, str]] | None = None,
    documents: list[dict[str, Any]] | None = None,
) -> Path:
    """A household's files with only what the RMD key reads. `accounts` pairs each row with its owner."""
    files = {
        ACCOUNTS_CSV: csv_text(ACCOUNTS_COLUMNS, [a for a, _ in accounts]),
        POSITIONS_CSV: csv_text(POSITIONS_COLUMNS, positions),
        CASH_CSV: csv_text(CASH_COLUMNS, cash_rows),
        TRANSACTIONS_CSV: csv_text(TRANSACTIONS_COLUMNS, transactions),
        BENEFICIARIES_CSV: csv_text(BENEFICIARIES_COLUMNS, beneficiaries or []),
        DOCUMENTS_INDEX: json_text({"documents": documents or []}),
        PORTFOLIO_HOUSEHOLD: json_text(
            {
                "household_id": "HH-0001",
                "household_membership": [
                    {"person_id": p, "name": f"Person {p}", "born": born} for p, born in people.items()
                ],
                "legal_ownership": [{"account_id": a["account_id"], "owner_ids": [owner]} for a, owner in accounts],
            }
        ),
    }
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root


A, B, C, D = "SYN-00010001", "SYN-00010002", "SYN-00010003", "SYN-00010004"


def first_year(root: Path, **extra: Any) -> Path:
    """P-1, born 1 June 1952, reaches 73 in 2025, the first distribution year: due by 1 April 2026.

    IRA A 250,000.00 + 15,000.00 cash = 265,000.00; IRA B 100,000.00 + 6,000.00 = 106,000.00; 401(k) C
    50,000.00 + 3,000.00 = 53,000.00; Roth D owes nothing. Uniform Lifetime factor at 73: 26.5.
    """
    return write_household(
        root,
        {"P-1": "1952-06-01", "P-2": "1955-01-01"},
        [
            (account(A, "traditional_ira"), "P-1"),
            (account(B, "traditional_ira"), "P-1"),
            (account(C, "401k"), "P-1"),
            (account(D, "roth_ira"), "P-1"),
        ],
        [position(A, "250000.00"), position(B, "100000.00"), position(C, "50000.00"), position(D, "80000.00")],
        [cash(A, "15000.00"), cash(B, "6000.00"), cash(C, "3000.00"), cash(D, "0.00")],
        [
            # Counts toward 2025: a first-year RMD may be paid by 1 April 2026.
            payout("T-1", A, "2026-03-02", "DISTRIBUTION", "-14000.00"),
            payout("T-2", C, "2025-12-01", "DISTRIBUTION", "-1500.00"),
            # A fee is not a distribution; a payment after 1 April 2026 is too late.
            payout("T-3", B, "2025-04-02", "FEE", "-250.00"),
            payout("T-4", C, "2026-04-10", "DISTRIBUTION", "-500.00"),
        ],
        **extra,
    )


def test_a_first_year_owner_meets_the_iras_together_but_not_the_401k(tmp_path: Path) -> None:
    key = household_rmd(first_year(tmp_path))
    # 265,000.00 / 26.5 = 10,000.00; 106,000.00 / 26.5 = 4,000.00; 53,000.00 / 26.5 = 2,000.00.
    assert [(a.account_id, a.balance, a.divisor, a.rmd) for a in key.accounts] == [
        (A, Decimal("265000.00"), Decimal("26.5"), Decimal("10000.00")),
        (B, Decimal("106000.00"), Decimal("26.5"), Decimal("4000.00")),
        (C, Decimal("53000.00"), Decimal("26.5"), Decimal("2000.00")),
    ]
    # The IRAs owe 14,000.00 together and T-1 paid it from A; the 401(k) owes 2,000.00 and paid 1,500.00.
    assert [(r.account_ids, r.rmd, r.taken, r.shortfall, str(r.deadline)) for r in key.requirements] == [
        ((A, B), Decimal("14000.00"), Decimal("14000.00"), Decimal("0"), "2026-04-01"),
        ((C,), Decimal("2000.00"), Decimal("1500.00"), Decimal("500.00"), "2026-04-01"),
    ]
    assert key.finding == "rmd_missed"
    assert key.total_shortfall == Decimal("500.00")


def test_after_the_first_year_only_payouts_in_2025_count(tmp_path: Path) -> None:
    # P-1, born 9 May 1947, is 78 in 2025 (Uniform Lifetime factor 22.0), well past the first year, so the
    # deadline is 31 December 2025. 220,000.00 / 22.0 = 10,000.00. The QCD of 4,000.00 in 2025 counts;
    # the 6,000.00 in February 2026 does not: 6,000.00 short.
    root = write_household(
        tmp_path,
        {"P-1": "1947-05-09"},
        [(account(A, "traditional_ira"), "P-1")],
        [position(A, "200000.00")],
        [cash(A, "20000.00")],
        [payout("T-1", A, "2025-06-01", "QCD", "-4000.00"), payout("T-2", A, "2026-02-01", "DISTRIBUTION", "-6000.00")],
    )
    key = household_rmd(root)
    (r,) = key.requirements
    assert (r.rmd, r.taken, r.shortfall, str(r.deadline)) == (
        Decimal("10000.00"),
        Decimal("4000.00"),
        Decimal("6000.00"),
        "2025-12-31",
    )


def test_an_owner_short_of_the_applicable_age_owes_nothing(tmp_path: Path) -> None:
    # Born 1953: 73 in 2026, so no 2025 RMD.
    root = write_household(
        tmp_path,
        {"P-1": "1953-01-15"},
        [(account(A, "traditional_ira"), "P-1")],
        [position(A, "1.00")],
        [cash(A, "0")],
        [],
    )
    key = household_rmd(root)
    assert key.requirements == ()
    assert key.finding == "all_rmds_met"


def inherited(root: Path, decedent: tuple[str, str], beneficiary_born: str = "1969-11-04") -> Path:
    return write_household(
        root,
        {"P-1": beneficiary_born},
        [(account(A, "inherited_ira", decedent), "P-1")],
        [position(A, "300000.00")],
        [cash(A, "5000.00")],
        [],
    )


def test_an_inherited_ira_after_the_required_beginning_date_owes_an_annual_rmd(tmp_path: Path) -> None:
    # The decedent, born 6 March 1945, was 70½ on 6 September 2015, so the required beginning date was
    # 1 April 2016, and the death on 15 January 2022 came after it. The beneficiary, born 4 November 1969,
    # is 54 in 2023: single life 32.5, less 2 for 2025 = 30.5. The decedent was 77 in 2022: 13.3, less
    # 3 = 10.3. The longer, 30.5, applies: 305,000.00 / 30.5 = 10,000.00, none taken.
    key = household_rmd(inherited(tmp_path, ("1945-03-06", "2022-01-15")))
    (a,) = key.accounts
    assert (a.age, a.divisor, a.rmd, str(a.deadline)) == (54, Decimal("30.5"), Decimal("10000.00"), "2025-12-31")
    assert key.total_shortfall == Decimal("10000.00")
    for figure in ("32.5", "13.3", "10.3", "30.5"):
        assert Decimal(figure) in key.table_figures


def test_an_inherited_ira_before_the_required_beginning_date_owes_no_annual_rmd(tmp_path: Path) -> None:
    # Born 15 September 1955, the decedent's required beginning date would have been 1 April 2029.
    key = household_rmd(inherited(tmp_path, ("1955-09-15", "2024-04-05"), beneficiary_born="1989-08-28"))
    assert key.requirements == ()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            {"beneficiaries": [spouse_beneficiary(A, "P-2")]},
            "Joint and Last Survivor",
        ),
        (
            {"documents": [{"kind": "form_w2", "person_id": "P-1", "valuation_date": "2025-12-31"}]},
            "wages",
        ),
    ],
)
def test_a_situation_the_key_does_not_cover_is_unsettled(tmp_path: Path, change: dict[str, Any], message: str) -> None:
    root = first_year(tmp_path, **change)
    if "beneficiaries" in change:
        # The spouse, born 1965, is 13 years younger than the owner.
        household = json.loads((root / PORTFOLIO_HOUSEHOLD).read_text())
        household["household_membership"][1]["born"] = "1965-01-01"
        (root / PORTFOLIO_HOUSEHOLD).write_text(json_text(household))
    with pytest.raises(UnsettledRmdError, match=message):
        household_rmd(root)


def test_a_beneficiary_close_in_age_to_the_decedent_is_unsettled(tmp_path: Path) -> None:
    # Born 1950, five years after the decedent: an eligible designated beneficiary, outside the ten-year rule.
    with pytest.raises(UnsettledRmdError, match="eligible designated beneficiary"):
        household_rmd(inherited(tmp_path, ("1945-03-06", "2022-01-15"), beneficiary_born="1950-01-01"))


def test_the_key_writes_as_json(tmp_path: Path) -> None:
    data = household_rmd(first_year(tmp_path)).to_dict()
    assert data["finding"] == "rmd_missed"
    assert data["total_shortfall"] == "500.00"
    assert data["requirements"][1] == {
        "owner_id": "P-1",
        "account_type": "401k",
        "account_ids": [C],
        "rmd": "2000.00",
        "deadline": "2026-04-01",
        "taken": "1500.00",
        "met": False,
        "shortfall": "500.00",
    }
    json.dumps(data)


def test_the_trap_household_missed_its_401k_rmd(book: Path) -> None:
    # HH-5271: Teodoro Villanueva, born 14 March 1952, reaches 73 in 2025 (factor 26.5), due 1 April 2026.
    # On 31 December 2024 (custodian/positions.csv and cash.csv):
    #   SYN-52710002 299,952.51 + 79,936.64 + 229,789.45 + 14,000.00 cash = 623,678.60 / 26.5 = 23,535.04
    #   SYN-52710003 119,858.56 + 84,985.20 + 5,500.00 cash = 210,343.76 / 26.5 = 7,937.50
    #   SYN-52710004 (401(k)) 189,848.96 + 139,995.00 + 7,500.00 cash = 337,343.96 / 26.5 = 12,729.96
    # T-5271-0044 paid 44,202.50 from SYN-52710002 on 4 December 2025, covering the IRAs' 31,472.54;
    # nothing came from the 401(k).
    key = household_rmd(book / household_dir("HH-5271"))
    assert [(a.account_id, a.balance, a.rmd) for a in key.accounts] == [
        ("SYN-52710002", Decimal("623678.60"), Decimal("23535.04")),
        ("SYN-52710003", Decimal("210343.76"), Decimal("7937.50")),
        ("SYN-52710004", Decimal("337343.96"), Decimal("12729.96")),
    ]
    assert [(r.account_ids, r.rmd, r.taken, r.shortfall) for r in key.requirements] == [
        (("SYN-52710002", "SYN-52710003"), Decimal("31472.54"), Decimal("44202.50"), Decimal("0")),
        (("SYN-52710004",), Decimal("12729.96"), Decimal("0"), Decimal("12729.96")),
    ]
    assert key.finding == "rmd_missed"


def test_the_twin_household_met_every_rmd(book: Path) -> None:
    # HH-5814: Prema Raghavan, born 22 July 1952, 73 in 2025 (26.5). On 31 December 2024:
    #   SYN-58140002 279,796.55 + 74,838.64 + 214,811.75 + 13,000.00 = 582,446.94 / 26.5 = 21,979.13
    #   SYN-58140003 109,797.44 + 79,978.32 + 5,000.00 = 194,775.76 / 26.5 = 7,350.03
    #   SYN-58140004 (401(k)) 174,976.00 + 129,981.24 + 7,000.00 = 311,957.24 / 26.5 = 11,771.97
    # T-5814-0046 paid 29,329.16 (21,979.13 + 7,350.03) from SYN-58140002; T-5814-0044 paid 11,771.97
    # from the 401(k).
    key = household_rmd(book / household_dir("HH-5814"))
    assert [(r.account_ids, r.rmd, r.taken, r.met) for r in key.requirements] == [
        (("SYN-58140002", "SYN-58140003"), Decimal("29329.16"), Decimal("29329.16"), True),
        (("SYN-58140004",), Decimal("11771.97"), Decimal("11771.97"), True),
    ]
    assert key.finding == "all_rmds_met"


@pytest.mark.parametrize("household", ["HH-5271", "HH-5814", "HH-6047", "HH-6590"])
def test_the_key_gives_the_same_answer_on_the_real_ticker_build(book: Path, real_book: Path, household: str) -> None:
    default = household_rmd(book / household_dir(household)).to_dict()
    real = household_rmd(real_book / household_dir(household)).to_dict()
    assert default == real


def test_one_beneficiarys_inherited_iras_from_one_decedent_are_met_together(tmp_path: Path) -> None:
    """Reviewer A, slice 9 round 1. Pub. 590-B, "More than one IRA": a beneficiary's inherited IRAs from the
    same decedent may be aggregated. The decedent and beneficiary of the case above, two accounts of
    305,000.00 each: 10,000.00 apiece at 30.5, 20,000.00 together, all of it paid from the first."""
    decedent = ("1945-03-06", "2022-01-15")
    root = write_household(
        tmp_path,
        {"P-1": "1969-11-04"},
        [(account(A, "inherited_ira", decedent), "P-1"), (account(B, "inherited_ira", decedent), "P-1")],
        [position(A, "300000.00"), position(B, "300000.00")],
        [cash(A, "5000.00"), cash(B, "5000.00")],
        [payout("T-0001-0001", A, "2025-11-03", "DISTRIBUTION", "-20000.00")],
    )
    key = household_rmd(root)
    (requirement,) = key.requirements
    assert requirement.account_ids == (A, B)
    assert (requirement.rmd, requirement.shortfall) == (Decimal("20000.00"), Decimal(0))
    assert key.total_shortfall == 0
