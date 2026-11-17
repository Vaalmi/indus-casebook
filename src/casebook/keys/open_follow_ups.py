"""The answer key for T-MTG-05: which households have a follow-up recorded in the CRM that has not happened by
the cutoff.

A follow-up is a CRM activity that commits someone to a step, and the record that the step happened is
read from the custodian's files or a later CRM activity, each known by the cutoff:

- a meeting or call that agrees a contribution to a traditional IRA, a conversion to a Roth IRA or a sale:
  the custodian's contribution to that IRA, its conversion into that Roth IRA, or a sale in the taxable
  account it names (the household's joint account where it names none), on or after the activity's date;
- a QCD request: a payout of the amount it names from the IRA it names, on or after its date;
- a distribution instruction: a distribution from the IRA it names (from the household's 401(k) when it is
  signed with the plan), of the amount it names when it names one, on or after its date;
- a request to the custodian to step up a deceased owner's basis: a step-up booked in the account it names
  (the custodian dates it the day of death, so any day counts);
- a beneficiary form sent to a client: a later activity recording the signed form received for each
  account it names;
- a beneficiary claim electing an inherited IRA: an inherited IRA of the decedent it names.

Every other activity kind the book holds records something that happened (a document, a confirmation, a
death, a retirement) and commits no one to anything. A note from the book's templates records a signed
agreement or an annual review with no change requested, and an agreement records a signing: neither
commits anyone to a later step. A kind of activity or note the key does not know, or a follow-up it cannot
read, raises rather than guess.

Shaped for `graders.household_list`: each household found is named with the IDs of its open activities.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from casebook.keys.figures import KeyFigure
from casebook.model.files import (
    ACCOUNTS_COLUMNS,
    ACCOUNTS_CSV,
    CHARITY_ACKNOWLEDGMENT,
    CONTRIBUTION,
    CONVERSION_IN,
    CRM_JSON,
    DEATH_NOTIFICATION,
    DISTRIBUTION,
    QCD,
    RSU_RELEASE,
    SELL,
    STEP_UP,
    TRANSACTIONS_COLUMNS,
    TRANSACTIONS_CSV,
    WITHDRAWAL,
    household_dir,
    read_csv,
    read_json,
    read_manifest,
)
from casebook.model.money import parse_decimal

MEETING, CALL = "meeting", "call"
QCD_REQUEST, DISTRIBUTION_INSTRUCTION = "qcd_request", "distribution_instruction"
CUSTODIAN_REQUEST = "custodian_request"
BENEFICIARY_FORM_SENT, BENEFICIARY_FORM_RECEIVED = "beneficiary_form_sent", "beneficiary_form_received"
BENEFICIARY_CLAIM = "beneficiary_claim"
# Activities that record what happened and commit no one to a later step.
RECORDS = frozenset(
    {
        "document_received",
        RSU_RELEASE,
        "retirement",
        CHARITY_ACKNOWLEDGMENT,
        DEATH_NOTIFICATION,
        "death_certificate",
        "custodian_confirmation",
        BENEFICIARY_FORM_RECEIVED,
    }
)
# The notes the book's templates write: a signed agreement, an annual review with no change requested.
NOTE_TEMPLATES = frozenset({"agreement_signed", "annual_review"})
NO_CHANGE = "No changes requested."
TRADITIONAL_IRA, ROTH_IRA, PLAN, INHERITED_IRA = "traditional_ira", "roth_ira", "401k", "inherited_ira"
TAXABLE = ("joint_taxable", "individual_taxable")
JOINT_TAXABLE = "joint_taxable"
# A distribution instruction signed with a 401(k) plan, which names no account.
PLAN_FORM = "with the 401(k) plan"

_ACCOUNT = re.compile(r"SYN-\d{8}")
_AMOUNT = re.compile(r"\$([\d,]+\.\d{2})")
_CONTRIBUTE = re.compile(r"contribution to (?:the |his |her |their )?new traditional IRA (SYN-\d{8})")
_CONVERT = re.compile(r"\bconvert\b.*?\bto (?:the |his |her |their )?Roth IRA (SYN-\d{8})")
_SELL = re.compile(r"\bto sell\b")
_STEP_UP = re.compile(r"stepped up")
_DECEDENT = re.compile(r"beneficiary of (.+?)'s traditional IRA, electing an inherited IRA")


class UnsettledFollowUpError(ValueError):
    """A CRM record the key cannot read as a follow-up or as none."""


@dataclass(frozen=True)
class FollowUp:
    """One follow-up the CRM records: what it commits to, and the record that it happened, if any."""

    activity_id: str
    kind: str
    recorded_on: date
    step: str
    evidence: tuple[str, ...]  # the transaction or activity IDs that show it happened; empty while it is open

    @property
    def open(self) -> bool:
        return not self.evidence


@dataclass(frozen=True)
class _Household:
    household_id: str
    kinds: Mapping[str, str]
    names: Mapping[str, str]  # each inherited IRA's decedent
    transactions: tuple[Mapping[str, str], ...]
    activities: tuple[Mapping[str, Any], ...]

    def accounts(self, *kinds: str) -> tuple[str, ...]:
        return tuple(sorted(a for a, k in self.kinds.items() if k in kinds))

    def done(
        self, types: tuple[str, ...], accounts: tuple[str, ...], since: date | None, amount: Decimal | None = None
    ) -> tuple[str, ...]:
        """The custodian's transactions of `types` in `accounts` on or after `since` (any day, for None), of
        `amount` when one is given."""
        return tuple(
            dict.fromkeys(
                t["transaction_id"]
                for t in self.transactions
                if t["type"] in types
                and t["account_id"] in accounts
                and (since is None or date.fromisoformat(t["trade_date"]) >= since)
                and (amount is None or abs(parse_decimal(t["amount"])) == amount)
            )
        )


def _known(record: Mapping[str, Any], as_of: date) -> bool:
    return date.fromisoformat(str(record["known_as_of"])) <= as_of


def _read(root: Path, as_of: date) -> tuple[_Household, tuple[Mapping[str, Any], ...]]:
    accounts = read_csv(root, ACCOUNTS_CSV, ACCOUNTS_COLUMNS)
    crm = read_json(root, CRM_JSON)
    household = _Household(
        household_id=str(crm["household_id"]),
        kinds={a["account_id"]: a["account_type"] for a in accounts},
        names={a["account_id"]: a["decedent"] for a in accounts if a["account_type"] == INHERITED_IRA},
        transactions=tuple(t for t in read_csv(root, TRANSACTIONS_CSV, TRANSACTIONS_COLUMNS) if _known(t, as_of)),
        activities=tuple(a for a in crm["activities"] if _known(a, as_of)),
    )
    return household, tuple(n for n in crm["notes"] if _known(n, as_of))


def _named(summary: str, hh: _Household, *kinds: str) -> tuple[str, ...]:
    return tuple(a for a in dict.fromkeys(_ACCOUNT.findall(summary)) if hh.kinds.get(a) in kinds)


def _amount(summary: str) -> Decimal | None:
    amounts = _AMOUNT.findall(summary)
    return parse_decimal(amounts[0].replace(",", "")) if amounts else None


def _accounts(activity: Mapping[str, Any], accounts: tuple[str, ...]) -> tuple[str, ...]:
    if not accounts:
        raise UnsettledFollowUpError(f"{activity['activity_id']}: names no account its step can happen in")
    return accounts


def _agreed(activity: Mapping[str, Any], hh: _Household) -> list[tuple[str, tuple[str, ...]]]:
    """A meeting's or call's agreed steps, each with the record that it happened."""
    summary, since = str(activity["summary"]), date.fromisoformat(str(activity["date"]))
    steps: list[tuple[str, tuple[str, ...]]] = []
    for ira in _CONTRIBUTE.findall(summary):
        steps.append((f"a contribution to {ira}", hh.done((CONTRIBUTION,), (ira,), since)))
    for roth in _CONVERT.findall(summary):
        steps.append((f"a conversion to {roth}", hh.done((CONVERSION_IN,), (roth,), since)))
    if _SELL.search(summary):
        where = _accounts(activity, _named(summary, hh, *TAXABLE) or hh.accounts(JOINT_TAXABLE))
        steps.append((f"a sale in {', '.join(where)}", hh.done((SELL,), where, since)))
    return steps


def _returned(hh: _Household, accounts: tuple[str, ...], since: date) -> tuple[str, ...]:
    """The activities recording a signed beneficiary form received for every one of `accounts`."""
    return tuple(
        str(a["activity_id"])
        for a in hh.activities
        if a["kind"] == BENEFICIARY_FORM_RECEIVED
        and date.fromisoformat(str(a["date"])) >= since
        and set(accounts) <= set(_ACCOUNT.findall(str(a["summary"])))
    )


def _follow_ups(activity: Mapping[str, Any], hh: _Household) -> list[tuple[str, tuple[str, ...]]]:
    """Each step the activity commits someone to, with the record that it happened (empty while open)."""
    kind, summary = str(activity["kind"]), str(activity["summary"])
    since = date.fromisoformat(str(activity["date"]))
    steps: list[tuple[str, tuple[str, ...]]] = []
    if kind in (MEETING, CALL):
        steps = _agreed(activity, hh)
    elif kind == QCD_REQUEST:
        iras = _accounts(activity, _named(summary, hh, TRADITIONAL_IRA))
        steps = [(f"a QCD from {', '.join(iras)}", hh.done((QCD, DISTRIBUTION), iras, since, _amount(summary)))]
    elif kind == DISTRIBUTION_INSTRUCTION:
        plan = hh.accounts(PLAN) if PLAN_FORM in summary else ()
        accounts = _accounts(activity, _named(summary, hh, TRADITIONAL_IRA, PLAN) or plan)
        paid = hh.done((DISTRIBUTION, WITHDRAWAL), accounts, since, _amount(summary))
        steps = [(f"a distribution from {', '.join(accounts)}", paid)]
    elif kind == CUSTODIAN_REQUEST and _STEP_UP.search(summary):
        accounts = _accounts(activity, _named(summary, hh, *TAXABLE))
        # The custodian books a step-up as of the date of death, before the request that asks for it.
        steps = [(f"a basis step-up in {', '.join(accounts)}", hh.done((STEP_UP,), accounts, None))]
    elif kind == BENEFICIARY_FORM_SENT:
        accounts = _accounts(activity, _named(summary, hh, TRADITIONAL_IRA, ROTH_IRA, PLAN))
        steps = [(f"the signed beneficiary form for {', '.join(accounts)}", _returned(hh, accounts, since))]
    elif kind == BENEFICIARY_CLAIM and (decedent := _DECEDENT.search(summary)):
        inherited = tuple(a for a, name in sorted(hh.names.items()) if name == decedent.group(1))
        steps = [(f"an inherited IRA from {decedent.group(1)}", inherited)]
    if not steps:
        raise UnsettledFollowUpError(f"{activity['activity_id']}: the key cannot read a follow-up in {summary!r}")
    return steps


def household_follow_ups(household_root: Path, as_of: date) -> tuple[str, tuple[FollowUp, ...]]:
    """The household's ID and every follow-up its CRM records by `as_of`, each with its evidence."""
    hh, notes = _read(household_root, as_of)
    for note in notes:
        if note.get("template") not in NOTE_TEMPLATES or (
            note["template"] == "annual_review" and NO_CHANGE not in str(note["text"])
        ):
            raise UnsettledFollowUpError(f"{note['note_id']}: a note the key cannot read for a follow-up")
    found: list[FollowUp] = []
    for activity in hh.activities:
        kind = str(activity["kind"])
        if kind in RECORDS:
            continue
        for step, evidence in _follow_ups(activity, hh):
            found.append(
                FollowUp(str(activity["activity_id"]), kind, date.fromisoformat(str(activity["date"])), step, evidence)
            )
    return hh.household_id, tuple(found)


@dataclass(frozen=True)
class OpenFollowUpsKey:
    as_of: date
    checked: tuple[str, ...]
    follow_ups: Mapping[str, tuple[FollowUp, ...]]
    # The CRM and the custodian's files settle every follow-up, so none is left unresolved.
    unresolved: tuple[str, ...] = ()
    # The answer turns on records, not amounts: the key derives no figure.
    computed_figures: tuple[KeyFigure, ...] = ()

    @property
    def found(self) -> Mapping[str, tuple[str, ...]]:
        """Each household with an open follow-up, with the IDs of its open activities."""
        open_ids = {
            h: tuple(dict.fromkeys(f.activity_id for f in follow_ups if f.open))
            for h, follow_ups in sorted(self.follow_ups.items())
        }
        return {h: ids for h, ids in open_ids.items() if ids}

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "found": {h: list(ids) for h, ids in self.found.items()},
            "unresolved": list(self.unresolved),
            "follow_ups": {
                h: [
                    {
                        "activity_id": f.activity_id,
                        "kind": f.kind,
                        "recorded_on": f.recorded_on.isoformat(),
                        "step": f.step,
                        "evidence": list(f.evidence),
                        "open": f.open,
                    }
                    for f in follow_ups
                ]
                for h, follow_ups in sorted(self.follow_ups.items())
                if follow_ups
            },
        }


def open_follow_ups_key(book: Path, as_of: date) -> OpenFollowUpsKey:
    checked = tuple(sorted(h.household_id for h in read_manifest(book).households))
    follow_ups: dict[str, tuple[FollowUp, ...]] = {}
    for household_id in checked:
        _, found = household_follow_ups(book / household_dir(household_id), as_of)
        follow_ups[household_id] = found
    return OpenFollowUpsKey(as_of, checked, follow_ups)
