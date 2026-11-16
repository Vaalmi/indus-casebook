"""CRM JSON: contacts, agreements, activities and notes.

A featured household's notes are the owner's hand-written file, once it exists; until then, and
for every background household, they render from named templates and slot values.
"""

from datetime import date
from typing import Any

from casebook.generate.notes import AUTHOR
from casebook.model.dates import SCENARIO_DATE
from casebook.model.files import CRM_JSON, SYNTHETIC, json_text
from casebook.model.household import CrmActivity, Household
from casebook.model.money import fmt
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
        # The slot values the text renders from: the note re-renders byte for byte from these and
        # its named template (docs/SPEC.md: no model-written text).
        "slots": dict(sorted(slots.items())),
        "text": TEMPLATES[template].format(**slots),
        "valuation_date": day.isoformat(),
        "known_as_of": day.isoformat(),
    }


def _activity(a: CrmActivity) -> dict[str, Any]:
    stated: dict[str, Any] = {
        "refers_to": a.refers_to.isoformat() if a.refers_to else None,
        "account_id": a.account_id,
        "security_id": a.security_id,
        "person_id": a.person_id,
        "units": fmt(a.units) if a.units is not None else None,
        "price": fmt(a.price) if a.price is not None else None,
        "amount": fmt(a.amount) if a.amount is not None else None,
    }
    return {
        "activity_id": a.activity_id,
        "date": a.day.isoformat(),
        "kind": a.kind,
        "summary": a.summary,
        **{k: v for k, v in stated.items() if v is not None},
        **({"price_label": SYNTHETIC} if a.price is not None else {}),
        "valuation_date": a.day.isoformat(),
        "known_as_of": a.day.isoformat(),
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
            "tax_id": p.tax_id,
            **({"died": p.died.isoformat()} if p.died else {}),
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
    # The review is held with the primary and the spouse still living on its date.
    primary = tuple(
        p.person_id
        for p in hh.members
        if p.relationship in ("primary", "spouse") and (p.died is None or p.died > ANNUAL_REVIEW)
    )
    dated.append(
        (
            ANNUAL_REVIEW,
            "annual_review",
            {"parties": _names(hh, primary), "accounts": ", ".join(a.account_id for a in hh.accounts)},
        )
    )
    dated.sort(key=lambda item: item[0])
    if context.notes is not None:
        notes = [
            {
                "note_id": n.note_id,
                "date": n.day.isoformat(),
                "author": AUTHOR,
                "text": n.text,
                "valuation_date": n.day.isoformat(),
                "known_as_of": n.day.isoformat(),
            }
            for n in sorted(context.notes.notes, key=lambda n: (n.day, n.note_id))
        ]
    else:
        notes = [_note(i, hh, day, template, slots) for i, (day, template, slots) in enumerate(dated, start=1)]
    activities = [_activity(a) for a in sorted(hh.crm_activities, key=lambda a: (a.day, a.activity_id))]
    crm = {
        "household_id": hh.household_id,
        "contacts": contacts,
        "agreements": agreements,
        "activities": activities,
        "notes": notes,
    }
    return {CRM_JSON: json_text(crm).encode()}
