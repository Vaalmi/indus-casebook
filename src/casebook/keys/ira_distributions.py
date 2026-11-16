"""The answer key for whether a household's 2025 IRA distributions agree between the custodian and the
CRM, and whether the year's RMD was met.

The CRM's charity acknowledgments say which payments were qualified charitable distributions: each
names the IRA, the amount and the day the charity received it. Each is matched to the custodian's
payout from that IRA on that day for that amount, and the custodian's type for it is compared: a
QCD the custodian recorded as an ordinary distribution is the disagreement. A QCD counts toward the
owner's RMD (26 U.S.C. § 408(d)(8)) however the custodian coded it, so the RMD is `keys.rmd`'s,
and the taxable IRA distributions are what left the IRAs less the QCDs, when the owner has no basis.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from casebook.keys.figures import KeyFigure
from casebook.keys.rmd import (
    PAYOUT_TYPES,
    TRADITIONAL_IRA,
    YEAR,
    YEAR_END,
    YEAR_START,
    HouseholdRmd,
    UnsettledRmdError,
    attains,
    household_rmd,
)
from casebook.model.files import (
    CHARITY_ACKNOWLEDGMENT,
    CRM_JSON,
    PORTFOLIO_TAX_PROFILE,
    QCD,
    read_json,
    read_transactions,
)
from casebook.model.money import fmt, parse_decimal
from casebook.rules import load_rules

type IraFinding = Literal["records_disagree", "records_agree"]
RECORDS_DISAGREE: IraFinding = "records_disagree"
RECORDS_AGREE: IraFinding = "records_agree"
ZERO = Decimal(0)


@dataclass(frozen=True)
class Qcd:
    """A QCD the CRM evidences, and the custodian's record of the same payment."""

    activity_id: str
    account_id: str
    owner_id: str
    paid_on: date
    amount: Decimal
    transaction_id: str
    recorded_as: str

    @property
    def agrees(self) -> bool:
        return self.recorded_as == QCD


@dataclass(frozen=True)
class IraDistributionsKey:
    household_id: str
    finding: IraFinding
    qcds: tuple[Qcd, ...]
    # What left the household's traditional IRAs in 2025, by the custodian's transactions.
    custodian_distributions: Decimal
    qcd_amount: Decimal
    taxable_distributions: Decimal
    rmd: Decimal
    rmd_met: bool
    rmds: HouseholdRmd
    computed_figures: tuple[KeyFigure, ...]
    table_figures: tuple[Decimal, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "household_id": self.household_id,
            "finding": self.finding,
            "qcds": [
                {
                    "activity_id": q.activity_id,
                    "account_id": q.account_id,
                    "paid_on": q.paid_on.isoformat(),
                    "amount": fmt(q.amount),
                    "transaction_id": q.transaction_id,
                    "recorded_as": q.recorded_as,
                }
                for q in self.qcds
            ],
            "custodian_distributions": fmt(self.custodian_distributions),
            "qcd_amount": fmt(self.qcd_amount),
            "taxable_distributions": fmt(self.taxable_distributions),
            "rmd": fmt(self.rmd),
            "rmd_met": self.rmd_met,
            "rmds": self.rmds.to_dict(),
            "computed_figures": [{"label": f.label, "value": fmt(f.value)} for f in self.computed_figures],
        }


def _basis(root: Path, person_id: str) -> Decimal:
    for row in read_json(root, PORTFOLIO_TAX_PROFILE).get("ira_basis", []):
        if str(row["person_id"]) == person_id:
            return parse_decimal(str(row["basis"]))
    return ZERO


def ira_distributions_key(household_root: Path) -> IraDistributionsKey:
    root = household_root
    rules = load_rules(YEAR)
    rmds = household_rmd(root, rules)
    iras = {a.account_id: a.owner_id for a in rmds.accounts if a.account_type == TRADITIONAL_IRA}
    payouts = [
        t
        for t in read_transactions(root)
        if t.account_id in iras and t.type in PAYOUT_TYPES and t.amount < 0 and YEAR_START <= t.trade_date <= YEAR_END
    ]
    qcds: list[Qcd] = []
    for activity in read_json(root, CRM_JSON)["activities"]:
        if activity["kind"] != CHARITY_ACKNOWLEDGMENT:
            continue
        account_id, amount = str(activity["account_id"]), parse_decimal(str(activity["amount"]))
        paid_on = date.fromisoformat(str(activity["refers_to"]))
        if account_id not in iras or paid_on.year != YEAR:
            continue
        matches = [t for t in payouts if t.account_id == account_id and t.trade_date == paid_on and -t.amount == amount]
        if len(matches) != 1:
            raise UnsettledRmdError(
                f"{activity['activity_id']}: the custodian shows {len(matches)} payouts of {fmt(amount)} from "
                f"{account_id} on {paid_on}, not one"
            )
        owner = rmds.person(iras[account_id])
        if paid_on < attains(owner.born, rules.value("qcd_age")):
            raise UnsettledRmdError(f"{activity['activity_id']}: {owner.name} was not yet 70½ on {paid_on}")
        paid = matches[0]
        qcds.append(
            Qcd(
                str(activity["activity_id"]),
                account_id,
                owner.person_id,
                paid_on,
                amount,
                paid.transaction_id,
                paid.type,
            )
        )
    evidenced = {q.transaction_id for q in qcds}
    unevidenced = [t.transaction_id for t in payouts if t.type == QCD and t.transaction_id not in evidenced]
    if unevidenced:
        raise UnsettledRmdError(f"the custodian records QCDs {unevidenced} that the CRM holds no acknowledgment for")
    for owner_id in {q.owner_id for q in qcds}:
        if sum((q.amount for q in qcds if q.owner_id == owner_id), ZERO) > rules.value("qcd_limit"):
            raise UnsettledRmdError(f"{owner_id}'s {YEAR} QCDs are above the limit")
    for owner_id in set(iras.values()):
        if _basis(root, owner_id) != 0:
            raise UnsettledRmdError(f"{owner_id} has IRA basis, so the taxable amount needs Form 8606")

    distributed = sum((-t.amount for t in payouts), ZERO)
    qcd_amount = sum((q.amount for q in qcds), ZERO)
    taxable = distributed - qcd_amount
    ira_requirements = [r for r in rmds.requirements if r.account_type == TRADITIONAL_IRA]
    rmd = sum((r.rmd for r in ira_requirements), ZERO)
    figures = [
        *rmds.computed_figures,
        KeyFigure(f"distributed from the IRAs in {YEAR}", distributed),
        KeyFigure(f"QCDs in {YEAR}", qcd_amount),
        KeyFigure(f"taxable IRA distributions in {YEAR}", taxable),
        KeyFigure(f"QCD limit, {YEAR}", rules.value("qcd_limit")),
        KeyFigure(f"IRA RMDs in {YEAR}", rmd),
    ]
    return IraDistributionsKey(
        household_id=rmds.household_id,
        finding=RECORDS_AGREE if all(q.agrees for q in qcds) else RECORDS_DISAGREE,
        qcds=tuple(qcds),
        custodian_distributions=distributed,
        qcd_amount=qcd_amount,
        taxable_distributions=taxable,
        rmd=rmd,
        rmd_met=all(r.met for r in ira_requirements),
        rmds=rmds,
        computed_figures=tuple(figures),
        table_figures=rmds.table_figures,
    )
