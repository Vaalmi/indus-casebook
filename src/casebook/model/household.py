"""A household's people, accounts and the five relations, kept as separate fields."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Person:
    person_id: str
    name: str
    born: date
    relationship: str
    email: str
    phone: str
    tax_id: str


@dataclass(frozen=True)
class Account:
    account_id: str
    account_type: str
    registration: str
    opened: date


@dataclass(frozen=True)
class Ownership:
    """Legal ownership: who holds title to an account."""

    account_id: str
    owner_ids: tuple[str, ...]


@dataclass(frozen=True)
class TaxUnit:
    tax_unit_id: str
    filing_status: str
    person_ids: tuple[str, ...]


@dataclass(frozen=True)
class BillingGroup:
    billing_group_id: str
    schedule_id: str
    account_ids: tuple[str, ...]


@dataclass(frozen=True)
class Disclosure:
    """Disclosure permission: whose accounts a person may be told about."""

    person_id: str
    account_ids: tuple[str, ...]


@dataclass(frozen=True)
class Agreement:
    agreement_id: str
    kind: str
    party_ids: tuple[str, ...]
    account_ids: tuple[str, ...]
    signed: date
    summary: str


@dataclass(frozen=True)
class Beneficiary:
    """A beneficiary designation on an account, as the custodian holds it."""

    account_id: str
    designation: str
    name: str
    relationship: str
    share: Decimal
    person_id: str | None
    designated: date


@dataclass(frozen=True)
class Restriction:
    """An IPS restriction the portfolio system records."""

    restriction_id: str
    text: str
    recorded: date


@dataclass(frozen=True)
class FeeTier:
    """Annual rate on the value up to `up_to`; None means no upper bound."""

    up_to: Decimal | None
    annual_rate: Decimal


@dataclass(frozen=True)
class FeeSchedule:
    schedule_id: str
    basis: str
    tiers: tuple[FeeTier, ...]


@dataclass(frozen=True)
class AllocationTarget:
    asset_class: str
    target: Decimal
    band: Decimal


@dataclass(frozen=True)
class LossCarryforward:
    """Capital loss carried into 2025 from the 2024 return, per tax unit."""

    tax_unit_id: str
    short_term: Decimal
    long_term: Decimal


@dataclass(frozen=True)
class IraBasis:
    """After-tax basis in a person's traditional IRAs at 31 December 2024 (Form 8606)."""

    person_id: str
    basis: Decimal


@dataclass(frozen=True)
class TaxProfile:
    known_as_of: date
    loss_carryforwards: tuple[LossCarryforward, ...]
    ira_basis: tuple[IraBasis, ...]


@dataclass(frozen=True)
class Household:
    household_id: str
    name: str
    archetype: int
    members: tuple[Person, ...]
    accounts: tuple[Account, ...]
    ownership: tuple[Ownership, ...]
    tax_units: tuple[TaxUnit, ...]
    billing_groups: tuple[BillingGroup, ...]
    disclosures: tuple[Disclosure, ...]
    agreements: tuple[Agreement, ...]
    beneficiaries: tuple[Beneficiary, ...]
    fee_schedule: FeeSchedule
    allocation: tuple[AllocationTarget, ...]
    asset_classes: dict[str, str]
    restrictions: tuple[Restriction, ...]
    concentration_limit: Decimal
    tax_profile: TaxProfile
    configured: date

    def account(self, account_id: str) -> Account:
        for account in self.accounts:
            if account.account_id == account_id:
                return account
        raise KeyError(account_id)

    def owners(self, account_id: str) -> tuple[str, ...]:
        for owned in self.ownership:
            if owned.account_id == account_id:
                return owned.owner_ids
        raise KeyError(account_id)

    def person(self, person_id: str) -> Person:
        for person in self.members:
            if person.person_id == person_id:
                return person
        raise KeyError(person_id)
