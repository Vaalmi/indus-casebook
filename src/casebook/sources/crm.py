"""CRM JSON: contacts, agreements and notes.

The notes here render from named templates and slot values. A featured household's
notes are replaced by the owner's hand-written files in slice 5.
"""

from datetime import date
from typing import Any

from casebook.model.dates import SCENARIO_DATE
from casebook.model.files import CRM_JSON, json_text
from casebook.model.household import Household
from casebook.sources.context import EmitContext

TEMPLATES = {
    "agreement_signed": (
        "Signed the {kind} agreement {agreement_id} with {parties}, covering accounts {accounts}. {summary}"
    ),
    "annual_review": (
        "Annual review with {parties}. Went through accounts {accounts}, the fee schedule and the IPS targets. "
        "No changes requested."
    ),
}
ANNUAL_REVIEW = date(2025, 10, 14)


def _names(hh: Household, person_ids: tuple[str, ...]) -> str:
    names = [hh.person(p).name for p in person_ids]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _note(number: int, hh: Household, day: date, template: str, slots: dict[str, str]) -> dict[str, Any]:
    return {
        "note_id": f"N-{hh.household_id.removeprefix('HH-')}-{number:02d}",
        "date": day.isoformat(),
        "author": "template",
        "template": template,
        "text": TEMPLATES[template].format(**slots),
        "valuation_date": day.isoformat(),
        "known_as_of": day.isoformat(),
    }


def emit(context: EmitContext) -> dict[str, bytes]:
    hh = context.script.household
    contacts = [
        {
            "person_id": p.person_id,
            "name": p.name,
            "relationship": p.relationship,
            "email": p.email,
            "phone": p.phone,
            "valuation_date": SCENARIO_DATE.isoformat(),
            "known_as_of": SCENARIO_DATE.isoformat(),
        }
        for p in hh.members
    ]
    agreements = [
        {
            "agreement_id": a.agreement_id,
            "kind": a.kind,
            "party_ids": list(a.party_ids),
            "account_ids": list(a.account_ids),
            "signed": a.signed.isoformat(),
            "summary": a.summary,
            "valuation_date": a.signed.isoformat(),
            "known_as_of": a.signed.isoformat(),
        }
        for a in hh.agreements
    ]
    dated: list[tuple[date, str, dict[str, str]]] = [
        (
            a.signed,
            "agreement_signed",
            {
                "kind": a.kind,
                "agreement_id": a.agreement_id,
                "parties": _names(hh, a.party_ids),
                "accounts": ", ".join(a.account_ids),
                "summary": a.summary,
            },
        )
        for a in hh.agreements
    ]
    primary = tuple(p.person_id for p in hh.members if p.relationship in ("primary", "spouse"))
    dated.append(
        (
            ANNUAL_REVIEW,
            "annual_review",
            {"parties": _names(hh, primary), "accounts": ", ".join(a.account_id for a in hh.accounts)},
        )
    )
    dated.sort(key=lambda item: item[0])
    notes = [_note(i, hh, day, template, slots) for i, (day, template, slots) in enumerate(dated, start=1)]
    crm = {"household_id": hh.household_id, "contacts": contacts, "agreements": agreements, "notes": notes}
    return {CRM_JSON: json_text(crm).encode()}
