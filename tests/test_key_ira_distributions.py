"""The IRA distributions key: the CRM's QCDs against the custodian's records, on hand-built files and on the
featured pair of archetype 6."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from casebook.keys.ira_distributions import ira_distributions_key
from casebook.keys.rmd import UnsettledRmdError
from casebook.model.files import CRM_JSON, PORTFOLIO_TAX_PROFILE, household_dir, json_text

from .test_key_rmd import A, account, cash, payout, position, write_household


def acknowledgment(amount: str, paid_on: str) -> dict[str, Any]:
    return {
        "activity_id": "CA-1",
        "kind": "charity_acknowledgment",
        "account_id": A,
        "amount": amount,
        "refers_to": paid_on,
        "date": "2025-07-01",
        "summary": "Acknowledgment letter from a charity.",
    }


def household(root: Path, qcd_type: str, activities: list[dict[str, Any]], basis: str = "0.00") -> Path:
    """P-1, born 9 May 1947 (78 in 2025, factor 22.0): IRA A worth 200,000.00 + 20,000.00 cash on 31 December
    2024, so 10,000.00 is due by 31 December 2025. 4,000.00 went to a charity on 2 June 2025, recorded as
    `qcd_type`, and 6,000.00 was distributed on 1 December 2025: 10,000.00 in all."""
    write_household(
        root,
        {"P-1": "1947-05-09"},
        [(account(A, "traditional_ira"), "P-1")],
        [position(A, "200000.00")],
        [cash(A, "20000.00")],
        [
            payout("T-1", A, "2025-06-02", qcd_type, "-4000.00"),
            payout("T-2", A, "2025-12-01", "DISTRIBUTION", "-6000.00"),
            payout("T-3", A, "2025-03-31", "FEE", "-500.00"),
        ],
    )
    (root / CRM_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / CRM_JSON).write_text(json_text({"activities": activities}))
    (root / PORTFOLIO_TAX_PROFILE).write_text(json_text({"ira_basis": [{"person_id": "P-1", "basis": basis}]}))
    return root


def test_a_qcd_the_custodian_recorded_as_a_distribution_is_the_disagreement(tmp_path: Path) -> None:
    key = ira_distributions_key(household(tmp_path, "DISTRIBUTION", [acknowledgment("4000.00", "2025-06-02")]))
    assert key.finding == "records_disagree"
    assert [(q.transaction_id, q.recorded_as, q.amount) for q in key.qcds] == [
        ("T-1", "DISTRIBUTION", Decimal("4000.00"))
    ]
    # 4,000.00 + 6,000.00 left the IRA (the fee is not a distribution); 6,000.00 is taxable; the RMD of
    # 220,000.00 / 22.0 = 10,000.00 was met, the QCD counting toward it.
    assert key.custodian_distributions == Decimal("10000.00")
    assert key.qcd_amount == Decimal("4000.00")
    assert key.taxable_distributions == Decimal("6000.00")
    assert (key.rmd, key.rmd_met) == (Decimal("10000.00"), True)


def test_a_qcd_recorded_as_one_agrees(tmp_path: Path) -> None:
    key = ira_distributions_key(household(tmp_path, "QCD", [acknowledgment("4000.00", "2025-06-02")]))
    assert key.finding == "records_agree"
    assert key.taxable_distributions == Decimal("6000.00")


@pytest.mark.parametrize(
    ("qcd_type", "activities", "basis", "message"),
    [
        ("DISTRIBUTION", [acknowledgment("4500.00", "2025-06-02")], "0.00", "payouts of 4500.00"),
        ("QCD", [], "0.00", "no acknowledgment"),
        ("QCD", [acknowledgment("4000.00", "2025-06-02")], "1200.00", "Form 8606"),
    ],
    ids=["acknowledgment matches no payout", "custodian QCD with no acknowledgment", "IRA basis"],
)
def test_records_the_key_cannot_settle_are_unsettled(
    tmp_path: Path, qcd_type: str, activities: list[dict[str, Any]], basis: str, message: str
) -> None:
    with pytest.raises(UnsettledRmdError, match=message):
        ira_distributions_key(household(tmp_path, qcd_type, activities, basis))


def test_the_trap_household_s_qcd_is_recorded_as_an_ordinary_distribution(book: Path) -> None:
    # HH-6047: CA-6047-02, the charity's acknowledgment, says $12,000.00 left IRA SYN-60470002 on
    # 2025-09-15; the custodian's T-6047-0016 that day is a DISTRIBUTION. With T-6047-0024's 9,659.73,
    # 21,659.73 left the IRA, 9,659.73 of it taxable. Bernard Lachance, born 9 May 1947, is 78 (22.0); on
    # 31 December 2024 the IRA held 189,890.36 + 209,687.80 + 64,935.90 + 12,000.00 cash = 476,514.06,
    # / 22.0 = 21,659.73, met exactly.
    key = ira_distributions_key(book / household_dir("HH-6047"))
    assert key.finding == "records_disagree"
    assert [(q.activity_id, q.transaction_id, q.recorded_as) for q in key.qcds] == [
        ("CA-6047-02", "T-6047-0016", "DISTRIBUTION")
    ]
    assert (key.custodian_distributions, key.qcd_amount, key.taxable_distributions) == (
        Decimal("21659.73"),
        Decimal("12000.00"),
        Decimal("9659.73"),
    )
    assert (key.rmd, key.rmd_met) == (Decimal("21659.73"), True)


def test_the_twin_household_s_qcd_is_recorded_as_one(book: Path) -> None:
    # HH-6590: CA-6590-02 acknowledges $15,000.00 paid on 2025-06-10, which the custodian records as
    # T-6590-0010, a QCD. With T-6590-0024's 9,882.45, 24,882.45 left the IRA, 9,882.45 taxable. Celestine
    # Abara, born 17 February 1947, is 78 (22.0); 219,859.09 + 239,643.20 + 74,911.56 + 13,000.00 cash =
    # 547,413.85, / 22.0 = 24,882.45, met.
    key = ira_distributions_key(book / household_dir("HH-6590"))
    assert key.finding == "records_agree"
    assert (key.custodian_distributions, key.qcd_amount, key.taxable_distributions) == (
        Decimal("24882.45"),
        Decimal("15000.00"),
        Decimal("9882.45"),
    )
    assert (key.rmd, key.rmd_met) == (Decimal("24882.45"), True)


def test_the_key_writes_as_json(book: Path) -> None:
    data = ira_distributions_key(book / household_dir("HH-6047")).to_dict()
    assert data["finding"] == "records_disagree"
    assert data["taxable_distributions"] == "9659.73"
    assert data["rmd_met"] is True
    json.dumps(data)
