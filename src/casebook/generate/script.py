"""A scripted household file (TOML), parsed at the boundary into typed parts."""

import tomllib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from casebook.generate.notes import NOTES_SUFFIX
from casebook.model.dates import parse_date
from casebook.model.events import UnsupportedEventError
from casebook.model.files import COMPARED_ACTIVITIES, DESIGNATIONS
from casebook.model.household import (
    Account,
    Agreement,
    AllocationTarget,
    Beneficiary,
    BillingGroup,
    CrmActivity,
    Decedent,
    Disclosure,
    FeeSchedule,
    FeeTier,
    Household,
    Income,
    IraBasis,
    LossCarryforward,
    Ownership,
    Person,
    Restriction,
    TaxProfile,
    TaxUnit,
)
from casebook.model.money import parse_decimal

# What a script may make happen. Dividends and fees follow from holdings and the schedule; the
# one stock split is a market event no featured household needs yet.
SCRIPTED_ACTIVITY = (
    "buy",
    "sell",
    "contribution",
    "withdrawal",
    "rmd",
    "qcd",
    "roth_conversion",
    "transfer",
    "rsu_vest",
    "death",
)
ACCOUNT_TYPES = ("joint_taxable", "individual_taxable", "traditional_ira", "roth_ira", "401k", "inherited_ira")
INCOME_KINDS = ("wages",)
# The fields each kind of activity needs, beyond its date and account.
ACTIVITY_FIELDS: dict[str, tuple[str, ...]] = {
    "buy": ("security_id", "units"),
    "sell": ("security_id", "units"),
    "contribution": ("amount",),
    "withdrawal": ("amount",),
    "rmd": ("amount", "tax_year", "withheld"),
    "qcd": ("amount", "charity"),
    "roth_conversion": ("amount", "to_account_id"),
    "transfer": ("to_account_id",),
    "rsu_vest": ("security_id", "units"),
    "death": ("person_id", "share"),
}
ROLES = ("trap", "twin")
TWIN_KINDS = ("clean", "near_miss", "unresolved")


class ScriptError(ValueError):
    def __init__(self, path: str, message: str) -> None:
        super().__init__(f"{path}: {message}")


@dataclass(frozen=True)
class Holding:
    lot_id: str
    security_id: str
    value: Decimal
    acquired: date
    basis_pct: Decimal


@dataclass(frozen=True)
class AccountScript:
    account_id: str
    cash: Decimal
    holdings: tuple[Holding, ...]


@dataclass(frozen=True)
class Activity:
    kind: str
    day: date
    account_id: str
    security_id: str | None = None
    units: Decimal | None = None
    amount: Decimal | None = None
    to_account_id: str | None = None
    tax_year: int | None = None
    withheld: Decimal | None = None
    charity: str | None = None
    person_id: str | None = None
    share: Decimal | None = None


@dataclass(frozen=True)
class PlantedSpec:
    item_id: str
    item_type: str
    # Whatever else the planter reads: the agreement for a missed breakpoint, the sale for a wash sale.
    details: dict[str, str]


@dataclass(frozen=True)
class TwinSpec:
    kind: str
    explanation: str


@dataclass(frozen=True)
class HouseholdScript:
    source: str
    household: Household
    pair: int
    role: str
    accounts: tuple[AccountScript, ...]
    activity: tuple[Activity, ...]
    planted: PlantedSpec | None
    twin: TwinSpec | None
    # A background household, drawn from the seed rather than written by hand (docs/SPEC.md: "one
    # of the other 80").
    background: bool = False


def _dec(raw: dict[str, Any], key: str) -> Decimal:
    return parse_decimal(str(raw[key]))


def _date(raw: dict[str, Any], key: str) -> date:
    value = raw[key]
    return value if isinstance(value, date) else parse_date(str(value))


def _ids(raw: dict[str, Any], key: str) -> tuple[str, ...]:
    return tuple(str(v) for v in raw[key])


def parse_script(raw: dict[str, Any], source: str) -> HouseholdScript:
    try:
        return _parse(raw, source)
    except UnsupportedEventError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise ScriptError(source, f"malformed ({error!r})") from error


def _parse(raw: dict[str, Any], source: str) -> HouseholdScript:
    accounts_raw: list[dict[str, Any]] = raw["accounts"]
    household = Household(
        household_id=str(raw["household_id"]),
        name=str(raw["name"]),
        archetype=int(raw["archetype"]),
        members=tuple(
            Person(
                str(p["person_id"]),
                str(p["name"]),
                _date(p, "born"),
                str(p["relationship"]),
                str(p["email"]),
                str(p["phone"]),
                str(p["tax_id"]),
                _date(p, "died") if "died" in p else None,
            )
            for p in raw["members"]
        ),
        accounts=tuple(
            Account(
                str(a["account_id"]),
                str(a["account_type"]),
                str(a["registration"]),
                _date(a, "opened"),
                Decedent(str(a["decedent"]["name"]), _date(a["decedent"], "born"), _date(a["decedent"], "died"))
                if "decedent" in a
                else None,
            )
            for a in accounts_raw
        ),
        ownership=tuple(Ownership(str(a["account_id"]), _ids(a, "owners")) for a in accounts_raw),
        tax_units=tuple(
            TaxUnit(str(t["tax_unit_id"]), str(t["filing_status"]), _ids(t, "person_ids")) for t in raw["tax_units"]
        ),
        billing_groups=tuple(
            BillingGroup(str(g["billing_group_id"]), str(g["schedule_id"]), _ids(g, "account_ids"))
            for g in raw["billing_groups"]
        ),
        disclosures=tuple(Disclosure(str(d["person_id"]), _ids(d, "account_ids")) for d in raw["disclosures"]),
        agreements=tuple(
            Agreement(
                str(a["agreement_id"]),
                str(a["kind"]),
                _ids(a, "party_ids"),
                _ids(a, "account_ids"),
                _date(a, "signed"),
                str(a["summary"]),
            )
            for a in raw["agreements"]
        ),
        beneficiaries=tuple(
            Beneficiary(
                str(b["account_id"]),
                str(b["designation"]),
                str(b["name"]),
                str(b["relationship"]),
                _dec(b, "share"),
                str(b["person_id"]) if "person_id" in b else None,
                _date(b, "designated"),
            )
            for b in raw.get("beneficiaries", [])
        ),
        income=tuple(
            Income(str(i["person_id"]), str(i["kind"]), str(i["payer"]), _dec(i, "amount"), int(i["year"]))
            for i in raw.get("income", [])
        ),
        crm_activities=tuple(
            CrmActivity(
                str(c["activity_id"]),
                _date(c, "date"),
                str(c["kind"]),
                str(c["summary"]),
                refers_to=_date(c, "refers_to") if "refers_to" in c else None,
                account_id=str(c["account_id"]) if "account_id" in c else None,
                security_id=str(c["security_id"]) if "security_id" in c else None,
                person_id=str(c["person_id"]) if "person_id" in c else None,
                units=_dec(c, "units") if "units" in c else None,
                price=_dec(c, "price") if "price" in c else None,
                amount=_dec(c, "amount") if "amount" in c else None,
            )
            for c in raw.get("crm_activities", [])
        ),
        fee_schedule=FeeSchedule(
            schedule_id=str(raw["fee_schedule"]["schedule_id"]),
            basis=str(raw["fee_schedule"]["basis"]),
            tiers=tuple(
                FeeTier(_dec(t, "up_to") if "up_to" in t else None, _dec(t, "annual_rate"))
                for t in raw["fee_schedule"]["tiers"]
            ),
        ),
        allocation=tuple(
            AllocationTarget(str(t["asset_class"]), _dec(t, "target"), _dec(t, "band")) for t in raw["ips"]["targets"]
        ),
        asset_classes={str(k): str(v) for k, v in raw["ips"]["asset_classes"].items()},
        restrictions=tuple(
            Restriction(str(r["restriction_id"]), str(r["text"]), _date(r, "recorded"))
            for r in raw["ips"]["restrictions"]
        ),
        concentration_limit=_dec(raw["ips"], "concentration_limit"),
        tax_profile=TaxProfile(
            known_as_of=_date(raw["tax_profile"], "known_as_of"),
            loss_carryforwards=tuple(
                LossCarryforward(str(c["tax_unit_id"]), _dec(c, "short_term"), _dec(c, "long_term"))
                for c in raw["tax_profile"]["loss_carryforwards"]
            ),
            ira_basis=tuple(IraBasis(str(b["person_id"]), _dec(b, "basis")) for b in raw["tax_profile"]["ira_basis"]),
        ),
        configured=_date(raw, "configured"),
    )
    accounts = tuple(
        AccountScript(
            account_id=str(a["account_id"]),
            cash=_dec(a, "cash"),
            holdings=tuple(
                Holding(
                    str(h["lot_id"]),
                    str(h["security_id"]),
                    _dec(h, "value"),
                    _date(h, "acquired"),
                    _dec(h, "basis_pct"),
                )
                for h in a["holdings"]
            ),
        )
        for a in accounts_raw
    )
    activity: list[Activity] = []
    for item in raw.get("activity", []):
        kind = str(item["type"])
        if kind not in SCRIPTED_ACTIVITY:
            raise UnsupportedEventError(kind)
        activity.append(
            Activity(
                kind=kind,
                day=_date(item, "date"),
                account_id=str(item["account_id"]),
                security_id=str(item["security_id"]) if "security_id" in item else None,
                units=_dec(item, "units") if "units" in item else None,
                amount=_dec(item, "amount") if "amount" in item else None,
                to_account_id=str(item["to_account_id"]) if "to_account_id" in item else None,
                tax_year=int(item["tax_year"]) if "tax_year" in item else None,
                withheld=_dec(item, "withheld") if "withheld" in item else None,
                charity=str(item["charity"]) if "charity" in item else None,
                person_id=str(item["person_id"]) if "person_id" in item else None,
                share=_dec(item, "share") if "share" in item else None,
            )
        )
    role = str(raw["role"])
    planted = raw.get("planted")
    twin = raw.get("twin")
    script = HouseholdScript(
        source=source,
        household=household,
        pair=int(raw["pair"]),
        role=role,
        accounts=accounts,
        activity=tuple(activity),
        planted=PlantedSpec(
            str(planted["item_id"]),
            str(planted["type"]),
            {str(k): str(v) for k, v in planted.items() if k not in ("item_id", "type")},
        )
        if planted
        else None,
        twin=TwinSpec(str(twin["kind"]), str(twin["explanation"])) if twin else None,
    )
    validate_script(script)
    return script


def validate_script(script: HouseholdScript) -> None:
    """Refuse a script, scripted or drawn, whose parts do not fit together."""
    hh = script.household
    if script.role not in ROLES:
        raise ScriptError(script.source, f"role {script.role!r} is not one of {ROLES}")
    if script.role == "trap" and (script.planted is None or script.twin is not None):
        raise ScriptError(script.source, "a trap has one planted item and no twin section")
    if script.role == "twin" and (script.twin is None or script.planted is not None):
        raise ScriptError(script.source, "a twin has a twin section and no planted item")
    if script.twin is not None and script.twin.kind not in TWIN_KINDS:
        raise ScriptError(script.source, f"twin kind {script.twin.kind!r} is not one of {TWIN_KINDS}")
    account_ids = [a.account_id for a in hh.accounts]
    for account in hh.accounts:
        if account.account_type not in ACCOUNT_TYPES:
            raise ScriptError(script.source, f"account type {account.account_type!r} is not one of {ACCOUNT_TYPES}")
        if (account.account_type == "inherited_ira") != (account.inherited_from is not None):
            raise ScriptError(
                script.source, f"{account.account_id}: an inherited IRA, and only one, names its decedent"
            )
    for activity in hh.crm_activities:
        stated = COMPARED_ACTIVITIES.get(activity.kind, ())
        missing = [f for f in stated if getattr(activity, f) is None]
        if missing:
            raise ScriptError(
                script.source, f"CRM activity {activity.activity_id} ({activity.kind}) needs {', '.join(missing)}"
            )
    for income in hh.income:
        if income.kind not in INCOME_KINDS or income.person_id not in {p.person_id for p in hh.members}:
            raise ScriptError(script.source, f"income {income.kind} names {income.person_id}, not a household member")
    grouped = sorted(a for g in hh.billing_groups for a in g.account_ids)
    if grouped != sorted(account_ids):
        raise ScriptError(script.source, "every account belongs to exactly one billing group")
    people = {p.person_id for p in hh.members}
    names = [p.name for p in hh.members]
    if len(set(names)) != len(names):
        raise ScriptError(script.source, "two household members share a name, so a record naming one is ambiguous")
    for owned in hh.ownership:
        if not set(owned.owner_ids) <= people:
            raise ScriptError(script.source, f"account {owned.account_id} has an owner outside the household")
    designated: dict[tuple[str, str], Decimal] = {}
    for b in hh.beneficiaries:
        if b.account_id not in account_ids:
            raise ScriptError(script.source, f"a beneficiary names unknown account {b.account_id}")
        if b.designation not in DESIGNATIONS:
            raise ScriptError(script.source, f"designation {b.designation!r} is not one of {DESIGNATIONS}")
        if b.person_id is not None and b.person_id not in people:
            raise ScriptError(script.source, f"beneficiary {b.name} names {b.person_id}, who is not in the household")
        key = (b.account_id, b.designation)
        designated[key] = designated.get(key, Decimal(0)) + b.share
    for (account_id, designation), total in sorted(designated.items()):
        if total != 100:
            raise ScriptError(script.source, f"{account_id}'s {designation} beneficiaries share {total}%, not 100%")
    for act in script.activity:
        if act.account_id not in account_ids:
            raise ScriptError(script.source, f"activity on {act.day} names unknown account {act.account_id}")
        if act.to_account_id is not None and act.to_account_id not in account_ids:
            raise ScriptError(script.source, f"{act.kind} on {act.day} names unknown account {act.to_account_id}")
        missing = [f for f in ACTIVITY_FIELDS[act.kind] if getattr(act, f) is None]
        if missing:
            raise ScriptError(script.source, f"{act.kind} on {act.day} needs {', '.join(missing)}")
        if act.kind in ("buy", "sell", "rsu_vest") and act.amount is not None:
            raise ScriptError(
                script.source, f"{act.kind} on {act.day}: buys and sells give units, cash flows give an amount"
            )
        if act.kind in ("contribution", "withdrawal") and act.units is not None:
            raise ScriptError(
                script.source, f"{act.kind} on {act.day}: buys and sells give units, cash flows give an amount"
            )
        if act.kind == "transfer" and (act.amount is None) == (act.units is None or act.security_id is None):
            raise ScriptError(script.source, f"transfer on {act.day} moves either units of a security or an amount")
        if act.kind == "death" and (act.person_id not in people or hh.person(act.person_id).died != act.day):
            raise ScriptError(
                script.source, f"death on {act.day} names {act.person_id}, who is not a member who died that day"
            )


def load_script(path: Path, root: Path) -> HouseholdScript:
    with path.open("rb") as handle:
        return parse_script(tomllib.load(handle), path.relative_to(root).as_posix())


def load_scripts(directory: Path) -> list[HouseholdScript]:
    paths = sorted(p for p in directory.rglob("*.toml") if not p.name.endswith(NOTES_SUFFIX))
    scripts = sorted((load_script(p, directory) for p in paths), key=lambda s: s.household.household_id)
    ids = [s.household.household_id for s in scripts]
    if len(set(ids)) != len(ids):
        raise ScriptError(directory.as_posix(), "two scripts share a household ID")
    return scripts
