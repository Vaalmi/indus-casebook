"""A scripted household file (TOML), parsed at the boundary into typed parts."""

import tomllib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from casebook.model.dates import parse_date
from casebook.model.events import UnsupportedEventError
from casebook.model.household import (
    Account,
    Agreement,
    AllocationTarget,
    BillingGroup,
    Disclosure,
    FeeSchedule,
    FeeTier,
    Household,
    Ownership,
    Person,
    TaxUnit,
)
from casebook.model.money import parse_decimal

SCRIPTED_ACTIVITY = ("buy", "sell", "contribution", "withdrawal")
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
    security_id: str | None
    units: Decimal | None
    amount: Decimal | None


@dataclass(frozen=True)
class PlantedSpec:
    item_id: str
    item_type: str
    agreement_id: str


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
            )
            for p in raw["members"]
        ),
        accounts=tuple(
            Account(str(a["account_id"]), str(a["account_type"]), str(a["registration"]), _date(a, "opened"))
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
        restrictions=tuple(str(r) for r in raw["ips"]["restrictions"]),
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
        planted=PlantedSpec(str(planted["item_id"]), str(planted["type"]), str(planted["agreement_id"]))
        if planted
        else None,
        twin=TwinSpec(str(twin["kind"]), str(twin["explanation"])) if twin else None,
    )
    _validate(script)
    return script


def _validate(script: HouseholdScript) -> None:
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
    grouped = sorted(a for g in hh.billing_groups for a in g.account_ids)
    if grouped != sorted(account_ids):
        raise ScriptError(script.source, "every account belongs to exactly one billing group")
    people = {p.person_id for p in hh.members}
    for owned in hh.ownership:
        if not set(owned.owner_ids) <= people:
            raise ScriptError(script.source, f"account {owned.account_id} has an owner outside the household")
    for act in script.activity:
        if act.account_id not in account_ids:
            raise ScriptError(script.source, f"activity on {act.day} names unknown account {act.account_id}")
        needs_units = act.kind in ("buy", "sell")
        if needs_units != (act.units is not None and act.security_id is not None) or needs_units == (
            act.amount is not None
        ):
            raise ScriptError(
                script.source, f"{act.kind} on {act.day}: buys and sells give units, cash flows give an amount"
            )


def load_script(path: Path, root: Path) -> HouseholdScript:
    with path.open("rb") as handle:
        return parse_script(tomllib.load(handle), path.relative_to(root).as_posix())


def load_scripts(directory: Path) -> list[HouseholdScript]:
    scripts = [load_script(p, directory) for p in sorted(directory.rglob("*.toml"))]
    ids = [s.household.household_id for s in scripts]
    if len(set(ids)) != len(ids):
        raise ScriptError(directory.as_posix(), "two scripts share a household ID")
    return scripts
