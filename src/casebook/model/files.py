"""The emitted file formats: paths, columns, the one way to write them, and typed readers.

Writers and readers share these definitions so a check reads exactly what the build
wrote. Every reader parses at the boundary and refuses a file whose columns differ.
"""

import csv
import io
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from casebook.model.dates import parse_date
from casebook.model.money import parse_decimal

SOURCE_SETS = ("custodian", "portfolio", "crm", "documents")

MANIFEST = "manifest.json"
METADATA = "metadata.json"
SECURITIES_CSV = "securities/securities.csv"
PRICES_CSV = "securities/prices_synthetic.csv"
REGISTRY = "sealed/registry.json"
SEALED_HOUSEHOLDS = "sealed/households.json"

ACCOUNTS_CSV = "custodian/accounts.csv"
POSITIONS_CSV = "custodian/positions.csv"
TRANSACTIONS_CSV = "custodian/transactions.csv"
TAX_LOTS_CSV = "custodian/tax_lots.csv"
REALIZED_CSV = "custodian/realized_lots.csv"
CASH_CSV = "custodian/cash.csv"
BENEFICIARIES_CSV = "custodian/beneficiaries.csv"
PORTFOLIO_TAX_PROFILE = "portfolio/tax_profile.json"
PORTFOLIO_HOUSEHOLD = "portfolio/household.json"
PORTFOLIO_BILLING = "portfolio/billing.json"
PORTFOLIO_IPS = "portfolio/ips.json"
PORTFOLIO_POSITIONS = "portfolio/positions.json"
CRM_JSON = "crm/crm.json"
DOCUMENTS_INDEX = "documents/index.json"

SYNTHETIC = "synthetic"
# A statement states its account's total in one line: "Total value on 2026-03-31: $1,234.56".
STATEMENT_TOTAL = "Total value on"
# metadata.json "securities": how a build names securities.
ALIASES = "aliases"
REAL_TICKERS = "real tickers"

BUY = "BUY"
SELL = "SELL"
DIVIDEND = "DIVIDEND"
CONTRIBUTION = "CONTRIBUTION"
WITHDRAWAL = "WITHDRAWAL"
FEE = "FEE"
DISTRIBUTION = "DISTRIBUTION"
QCD = "QCD"
CONVERSION_OUT = "CONVERSION_OUT"
CONVERSION_IN = "CONVERSION_IN"
TRANSFER_OUT = "TRANSFER_OUT"
TRANSFER_IN = "TRANSFER_IN"
RSU_VEST = "RSU_VEST"
SPLIT = "SPLIT"
STEP_UP = "STEP_UP"
TRANSACTION_TYPES = (
    BUY,
    SELL,
    DIVIDEND,
    CONTRIBUTION,
    WITHDRAWAL,
    FEE,
    DISTRIBUTION,
    QCD,
    CONVERSION_OUT,
    CONVERSION_IN,
    TRANSFER_OUT,
    TRANSFER_IN,
    RSU_VEST,
    SPLIT,
    STEP_UP,
)
# How a transaction's units column moves a holding; other types leave units alone.
UNIT_SIGNS = {BUY: 1, SELL: -1, TRANSFER_IN: 1, TRANSFER_OUT: -1, RSU_VEST: 1, SPLIT: 1}

SECURITIES_COLUMNS = ("security_id", "security")
PRICES_COLUMNS = ("security_id", "security", "price", "price_label", "valuation_date", "known_as_of")
ACCOUNTS_COLUMNS = (
    "account_id",
    "account_type",
    "registration",
    "owners",
    "opened",
    # An inherited IRA's decedent, whose dates the ten-year rule turns on; blank for other accounts.
    "decedent",
    "decedent_born",
    "decedent_died",
    "valuation_date",
    "known_as_of",
)
POSITIONS_COLUMNS = (
    "account_id",
    "security_id",
    "security",
    "units",
    "price",
    "price_label",
    "market_value",
    "valuation_date",
    "known_as_of",
)
TRANSACTIONS_COLUMNS = (
    "transaction_id",
    "account_id",
    "trade_date",
    "settle_date",
    "type",
    "security_id",
    "security",
    "units",
    "lot_id",
    "price",
    "price_label",
    "amount",
    "description",
    "valuation_date",
    "known_as_of",
)
TAX_LOTS_COLUMNS = (
    "account_id",
    "lot_id",
    "security_id",
    "security",
    "acquired_date",
    "units",
    "cost_basis",
    "valuation_date",
    "known_as_of",
)
REALIZED_COLUMNS = (
    "transaction_id",
    "account_id",
    "lot_id",
    "security_id",
    "security",
    "acquired_date",
    "sold_date",
    "units",
    "cost_basis",
    "proceeds",
    "gain",
    "valuation_date",
    "known_as_of",
)
CASH_COLUMNS = ("account_id", "settled_cash", "unsettled_cash", "valuation_date", "known_as_of")
BENEFICIARIES_COLUMNS = (
    "account_id",
    "designation",
    "name",
    "relationship",
    "share_percent",
    "person_id",
    "valuation_date",
    "known_as_of",
)
DESIGNATIONS = ("primary", "contingent")
# CRM activities that state a fact another source states too, and the fields each must give so
# "sources agree" can compare them with the custodian.
RSU_RELEASE = "rsu_release_confirmation"
CHARITY_ACKNOWLEDGMENT = "charity_acknowledgment"
DEATH_NOTIFICATION = "death_notification"
COMPARED_ACTIVITIES: dict[str, tuple[str, ...]] = {
    RSU_RELEASE: ("refers_to", "account_id", "security_id", "units", "price"),
    CHARITY_ACKNOWLEDGMENT: ("refers_to", "account_id", "amount"),
    DEATH_NOTIFICATION: ("refers_to", "person_id"),
}


class FileFormatError(ValueError):
    def __init__(self, path: str, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path


def household_dir(household_id: str) -> str:
    return f"households/{household_id}"


def event_log_path(household_id: str) -> str:
    return f"sealed/{household_id}/events.json"


# Writing. JSON has sorted keys and a final newline; CSV uses "\n" line endings.


def json_text(data: Any) -> str:
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def csv_text(columns: Sequence[str], rows: Iterable[Mapping[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


# Reading.


def read_json(root: Path, relative: str) -> Any:
    try:
        return json.loads((root / relative).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise FileFormatError(relative, "missing") from error
    except json.JSONDecodeError as error:
        raise FileFormatError(relative, f"not JSON ({error})") from error


def read_csv(root: Path, relative: str, columns: Sequence[str]) -> list[dict[str, str]]:
    try:
        text = (root / relative).read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise FileFormatError(relative, "missing") from error
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != tuple(columns):
        raise FileFormatError(relative, f"columns {reader.fieldnames} are not {list(columns)}")
    return list(reader)


def _decimal(path: str, line: int, name: str, text: str) -> Decimal:
    try:
        return parse_decimal(text)
    except ValueError as error:
        raise FileFormatError(path, f"line {line}: {name} {error}") from error


def _date(path: str, line: int, name: str, text: str) -> date:
    try:
        return parse_date(text)
    except ValueError as error:
        raise FileFormatError(path, f"line {line}: {name} is not a date: {text!r}") from error


@dataclass(frozen=True)
class PositionRow:
    line: int
    account_id: str
    security_id: str
    units: Decimal
    price: Decimal
    market_value: Decimal
    valuation_date: date


@dataclass(frozen=True)
class TransactionRow:
    line: int
    transaction_id: str
    account_id: str
    trade_date: date
    settle_date: date
    type: str
    security_id: str
    units: Decimal | None
    lot_id: str
    price: Decimal | None
    amount: Decimal
    description: str


@dataclass(frozen=True)
class TaxLotRow:
    line: int
    account_id: str
    lot_id: str
    security_id: str
    acquired_date: date
    units: Decimal
    cost_basis: Decimal
    valuation_date: date


@dataclass(frozen=True)
class RealizedRow:
    line: int
    transaction_id: str
    account_id: str
    lot_id: str
    security_id: str
    acquired_date: date
    sold_date: date
    units: Decimal
    cost_basis: Decimal
    proceeds: Decimal
    gain: Decimal


@dataclass(frozen=True)
class AccountRow:
    line: int
    account_id: str


@dataclass(frozen=True)
class CashRow:
    line: int
    account_id: str
    settled_cash: Decimal
    unsettled_cash: Decimal
    valuation_date: date


# CSV line numbers count the header as line 1, so the first row is line 2.


def read_positions(household_root: Path) -> list[PositionRow]:
    path = POSITIONS_CSV
    return [
        PositionRow(
            line=i,
            account_id=r["account_id"],
            security_id=r["security_id"],
            units=_decimal(path, i, "units", r["units"]),
            price=_decimal(path, i, "price", r["price"]),
            market_value=_decimal(path, i, "market_value", r["market_value"]),
            valuation_date=_date(path, i, "valuation_date", r["valuation_date"]),
        )
        for i, r in enumerate(read_csv(household_root, path, POSITIONS_COLUMNS), start=2)
    ]


def read_transactions(household_root: Path) -> list[TransactionRow]:
    path = TRANSACTIONS_CSV
    return [
        TransactionRow(
            line=i,
            transaction_id=r["transaction_id"],
            account_id=r["account_id"],
            trade_date=_date(path, i, "trade_date", r["trade_date"]),
            settle_date=_date(path, i, "settle_date", r["settle_date"]),
            type=r["type"],
            security_id=r["security_id"],
            units=_decimal(path, i, "units", r["units"]) if r["units"] else None,
            lot_id=r["lot_id"],
            price=_decimal(path, i, "price", r["price"]) if r["price"] else None,
            amount=_decimal(path, i, "amount", r["amount"]),
            description=r["description"],
        )
        for i, r in enumerate(read_csv(household_root, path, TRANSACTIONS_COLUMNS), start=2)
    ]


def read_tax_lots(household_root: Path) -> list[TaxLotRow]:
    path = TAX_LOTS_CSV
    return [
        TaxLotRow(
            line=i,
            account_id=r["account_id"],
            lot_id=r["lot_id"],
            security_id=r["security_id"],
            acquired_date=_date(path, i, "acquired_date", r["acquired_date"]),
            units=_decimal(path, i, "units", r["units"]),
            cost_basis=_decimal(path, i, "cost_basis", r["cost_basis"]),
            valuation_date=_date(path, i, "valuation_date", r["valuation_date"]),
        )
        for i, r in enumerate(read_csv(household_root, path, TAX_LOTS_COLUMNS), start=2)
    ]


def read_realized(household_root: Path) -> list[RealizedRow]:
    path = REALIZED_CSV
    return [
        RealizedRow(
            line=i,
            transaction_id=r["transaction_id"],
            account_id=r["account_id"],
            lot_id=r["lot_id"],
            security_id=r["security_id"],
            acquired_date=_date(path, i, "acquired_date", r["acquired_date"]),
            sold_date=_date(path, i, "sold_date", r["sold_date"]),
            units=_decimal(path, i, "units", r["units"]),
            cost_basis=_decimal(path, i, "cost_basis", r["cost_basis"]),
            proceeds=_decimal(path, i, "proceeds", r["proceeds"]),
            gain=_decimal(path, i, "gain", r["gain"]),
        )
        for i, r in enumerate(read_csv(household_root, path, REALIZED_COLUMNS), start=2)
    ]


def read_accounts(household_root: Path) -> list[AccountRow]:
    rows = read_csv(household_root, ACCOUNTS_CSV, ACCOUNTS_COLUMNS)
    return [AccountRow(line=i, account_id=r["account_id"]) for i, r in enumerate(rows, start=2)]


def read_cash(household_root: Path) -> list[CashRow]:
    path = CASH_CSV
    return [
        CashRow(
            line=i,
            account_id=r["account_id"],
            settled_cash=_decimal(path, i, "settled_cash", r["settled_cash"]),
            unsettled_cash=_decimal(path, i, "unsettled_cash", r["unsettled_cash"]),
            valuation_date=_date(path, i, "valuation_date", r["valuation_date"]),
        )
        for i, r in enumerate(read_csv(household_root, path, CASH_COLUMNS), start=2)
    ]


@dataclass(frozen=True)
class ManifestHousehold:
    household_id: str
    archetype: int
    state: str


@dataclass(frozen=True)
class Manifest:
    version: str
    seed: int
    households: tuple[ManifestHousehold, ...]
    files: dict[str, str]


def read_manifest(book_root: Path) -> Manifest:
    raw = read_json(book_root, MANIFEST)
    try:
        return Manifest(
            version=str(raw["version"]),
            seed=int(raw["seed"]),
            households=tuple(
                ManifestHousehold(str(h["household_id"]), int(h["archetype"]), str(h["state"]))
                for h in raw["households"]
            ),
            files={str(k): str(v) for k, v in raw["files"].items()},
        )
    except (KeyError, TypeError, ValueError) as error:
        raise FileFormatError(MANIFEST, f"malformed ({error})") from error
