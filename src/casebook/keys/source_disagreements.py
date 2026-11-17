"""The answer key for the book-level sweep: which households' records hold an identifier, beneficiary or
ownership fact that two sources state differently.

Each fact is compared wherever two sources both state it:

- ownership: an account's owners in the custodian's accounts, the portfolio system's legal ownership, the
  quarterly statements and the tax documents' recipient line; the statements' registration;
- people: each person's name, relationship and date of death in the CRM's contacts and the portfolio system,
  and a death the CRM records (a death notification, a death certificate) against the portfolio system and
  the custodian's inherited-IRA registration;
- identifiers: the taxpayer ID on each tax document against the CRM's tax ID for the person it names;
- beneficiaries: the custodian's designations against the household member a designation names, and against
  what the CRM records of them (a change received, a form sent while the old designation stands, a
  beneficiary's claim on an inherited IRA).

Each disagreement is named by its record: the account, or the person where no account is involved. A planted
difference that the registry records is still a difference in the files, so it is found like any other.
"""

import io
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from casebook.keys.figures import KeyFigure
from casebook.model.files import (
    ACCOUNTS_COLUMNS,
    ACCOUNTS_CSV,
    BENEFICIARIES_COLUMNS,
    BENEFICIARIES_CSV,
    CRM_JSON,
    DEATH_NOTIFICATION,
    DOCUMENTS_INDEX,
    PORTFOLIO_HOUSEHOLD,
    household_dir,
    read_csv,
    read_json,
    read_manifest,
)
from casebook.model.identifiers import account_numbers

STATEMENT = "quarterly_statement"
ACCOUNT_FORMS = ("form_1099_composite", "form_1099_r")
PERSON_FORMS = ("form_w2", "form_ssa_1099")
PRIMARY = "primary"
DEATH_CERTIFICATE = "death_certificate"
FORM_RECEIVED, FORM_SENT, CLAIM = "beneficiary_form_received", "beneficiary_form_sent", "beneficiary_claim"
OWNER_SEPARATOR = ";"

_ACCOUNT_LINE = re.compile(r"^Account (\S+): (.+)$", re.MULTILINE)
_OWNERS_LINE = re.compile(r"^Owners: (.*)$", re.MULTILINE)
_RECIPIENT_LINE = re.compile(r"^Recipient: (.*)$", re.MULTILINE)
_TIN = re.compile(r"(?:TIN|social security number): (\d{3}-\d{2}-\d{4})")
_NEW_PRIMARIES = re.compile(r": (.+?) as primary beneficiar(?:y|ies)\b")
_STILL_NAMES = re.compile(r"which still names (.+?) as primary beneficiary")
_CERTIFICATE = re.compile(r"received for (.+?), .*born (\d{4}-\d{2}-\d{2}), died (\d{4}-\d{2}-\d{2})")
_CLAIM = re.compile(r"signed by (.+?), .*primary beneficiary of (.+?)'s ")


class UnreadableRecordError(ValueError):
    """A record states its fact in a form this key cannot read."""


@dataclass(frozen=True)
class Disagreement:
    record_id: str
    what: str


@dataclass(frozen=True)
class SourceDisagreementsKey:
    checked: tuple[str, ...]
    disagreements: Mapping[str, tuple[Disagreement, ...]]
    # Every fact compared is stated outright in both sources, so the files settle every household.
    unresolved: tuple[str, ...] = ()
    # The question turns on records, not amounts: the key computes no figure.
    computed_figures: tuple[KeyFigure, ...] = ()

    @property
    def found(self) -> Mapping[str, tuple[str, ...]]:
        return {
            h: tuple(dict.fromkeys(d.record_id for d in found))
            for h, found in sorted(self.disagreements.items())
            if found
        }

    def to_dict(self) -> dict[str, Any]:
        found = self.found
        return {
            "checked": list(self.checked),
            "found": {h: list(ids) for h, ids in found.items()},
            "unresolved": list(self.unresolved),
            "cleared": sorted(set(self.checked) - set(found)),
            "disagreements": {
                h: [{"record_id": d.record_id, "what": d.what} for d in self.disagreements[h]] for h in found
            },
        }


def _names(text: str) -> frozenset[str]:
    """People named in a list: "A; B", "A and B" or "A, B and C"."""
    parts = re.split(r";|,| and ", text)
    return frozenset(p.strip() for p in parts if p.strip())


def _pdf_text(path: Path) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(path.read_bytes())).pages)


def _search(pattern: re.Pattern[str], text: str, where: str) -> re.Match[str]:
    found = pattern.search(text)
    if found is None:
        raise UnreadableRecordError(f"{where}: no match for {pattern.pattern!r}")
    return found


def household_disagreements(root: Path) -> tuple[Disagreement, ...]:
    found: list[Disagreement] = []
    household = read_json(root, PORTFOLIO_HOUSEHOLD)
    crm = read_json(root, CRM_JSON)
    members = {str(m["person_id"]): m for m in household["household_membership"]}
    contacts = {str(c["person_id"]): c for c in crm["contacts"]}
    member_names = {p: str(m["name"]) for p, m in members.items()}
    accounts = {a["account_id"]: a for a in read_csv(root, ACCOUNTS_CSV, ACCOUNTS_COLUMNS)}
    owners = {a: _names(row["owners"]) for a, row in accounts.items()}

    # Ownership: the custodian against the portfolio system.
    legal = {
        str(o["account_id"]): frozenset(member_names.get(str(p), str(p)) for p in o["owner_ids"])
        for o in household["legal_ownership"]
    }
    for account in sorted(set(owners) | set(legal)):
        if owners.get(account) != legal.get(account):
            held, listed = sorted(owners.get(account, ())), sorted(legal.get(account, ()))
            what = f"owners {held} at the custodian, {listed} in the portfolio system"
            found.append(Disagreement(account, what))

    # People: the CRM against the portfolio system.
    for person in sorted(set(members) | set(contacts)):
        stated = [
            (str(x["name"]), str(x["relationship"]), str(x.get("died", ""))) if x else None
            for x in (contacts.get(person), members.get(person))
        ]
        if stated[0] != stated[1]:
            found.append(Disagreement(person, f"{stated[0]} in the CRM, {stated[1]} in the portfolio system"))

    # The documents: statements' owners and registration, tax documents' recipients and taxpayer IDs.
    tax_ids = {p: str(c.get("tax_id", "")) for p, c in contacts.items()}
    tax_id_of_name = {str(c["name"]): str(c.get("tax_id", "")) for c in crm["contacts"]}
    for document in read_json(root, DOCUMENTS_INDEX)["documents"]:
        kind, where = str(document["kind"]), f"documents/{document['file']}"
        if kind not in (STATEMENT, *ACCOUNT_FORMS, *PERSON_FORMS):
            continue
        text = _pdf_text(root / where)
        if kind == STATEMENT:
            account = str(document["account_id"])
            header = _search(_ACCOUNT_LINE, text, where)
            if header.group(1) == account and header.group(2).strip() != accounts[account]["registration"]:
                found.append(Disagreement(account, f"{where} registers it as {header.group(2).strip()}"))
            named = _names(_search(_OWNERS_LINE, text, where).group(1))
            if named != owners.get(account):
                found.append(Disagreement(account, f"{where} names owners {sorted(named)}"))
            continue
        tin = _search(_TIN, text, where).group(1)
        if kind in ACCOUNT_FORMS:
            account = str(document["account_id"])
            named = _names(_search(_RECIPIENT_LINE, text, where).group(1))
            if named != owners.get(account):
                found.append(Disagreement(account, f"{where} names recipients {sorted(named)}"))
            if tin not in {tax_id_of_name.get(n) for n in named}:
                found.append(Disagreement(account, f"{where} carries taxpayer ID {tin}, no recipient's in the CRM"))
        else:
            person = str(document["person_id"])
            if tin != tax_ids.get(person):
                found.append(Disagreement(person, f"{where} carries taxpayer ID {tin}, the CRM {tax_ids.get(person)}"))

    # Deaths the CRM records.
    inherited = {a: row for a, row in accounts.items() if row["decedent"]}
    for activity in crm["activities"]:
        kind, ref, summary = str(activity["kind"]), str(activity["activity_id"]), str(activity["summary"])
        if kind == DEATH_NOTIFICATION:
            person = str(activity["person_id"])
            died = str(members.get(person, {}).get("died", ""))
            if died != str(activity["refers_to"]):
                what = f"{ref} records a death on {activity['refers_to']}, the portfolio system {died or 'none'}"
                found.append(Disagreement(person, what))
        elif kind == DEATH_CERTIFICATE:
            name, born, died = _search(_CERTIFICATE, summary, ref).groups()
            for account, row in sorted(inherited.items()):
                if row["decedent"] == name and (row["decedent_born"], row["decedent_died"]) != (born, died):
                    custodian = f"{row['decedent_born']}, {row['decedent_died']}"
                    what = f"{ref} gives born {born}, died {died}; the custodian {custodian}"
                    found.append(Disagreement(account, what))

    # Beneficiaries.
    designations: dict[str, frozenset[str]] = {}
    for row in read_csv(root, BENEFICIARIES_CSV, BENEFICIARIES_COLUMNS):
        person = row["person_id"]
        if person and member_names.get(person) != row["name"]:
            named = f"{row['name']} at the custodian, {member_names.get(person)} in the portfolio system"
            what = f"{row['designation']} beneficiary {person} is {named}"
            found.append(Disagreement(row["account_id"], what))
        if row["designation"] == PRIMARY:
            designations[row["account_id"]] = designations.get(row["account_id"], frozenset()) | {row["name"]}
    for activity in crm["activities"]:
        kind, ref, summary = str(activity["kind"]), str(activity["activity_id"]), str(activity["summary"])
        if kind in (FORM_RECEIVED, FORM_SENT):
            pattern = _NEW_PRIMARIES if kind == FORM_RECEIVED else _STILL_NAMES
            named = _names(_search(pattern, summary, ref).group(1))
            for account in account_numbers(summary.split(":")[0] if kind == FORM_RECEIVED else summary):
                if designations.get(account, frozenset()) != named:
                    what = f"{ref} names primary {sorted(named)}, the custodian {sorted(designations.get(account, ()))}"
                    found.append(Disagreement(account, what))
        elif kind == CLAIM:
            claimant, decedent = _search(_CLAIM, summary, ref).groups()
            held = [a for a, row in inherited.items() if row["decedent"] == decedent and claimant in owners[a]]
            if not held:
                found.append(
                    Disagreement(
                        ref, f"{ref}: {claimant} claims {decedent}'s IRA; the custodian holds no such inherited IRA"
                    )
                )
    return tuple(found)


def source_disagreements_key(book: Path) -> SourceDisagreementsKey:
    checked = tuple(h.household_id for h in read_manifest(book).households)
    return SourceDisagreementsKey(checked, {h: household_disagreements(book / household_dir(h)) for h in checked})
