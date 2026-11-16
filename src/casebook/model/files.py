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
CASH_CSV = "custodian/cash.csv"
PORTFOLIO_HOUSEHOLD = "portfolio/household.json"
PORTFOLIO_BILLING = "portfolio/billing.json"
PORTFOLIO_IPS = "portfolio/ips.json"
PORTFOLIO_POSITIONS = "portfolio/positions.json"
CRM_JSON = "crm/crm.json"
DOCUMENTS_INDEX = "documents/index.json"

SYNTHETIC = "synthetic"
# metadata.json "securities": how a build names securities.
ALIASES = "aliases"
REAL_TICKERS = "real tickers"

BUY = "BUY"
SELL = "SELL"
DIVIDEND = "DIVIDEND"
CONTRIBUTION = "CONTRIBUTION"
WITHDRAWAL = "WITHDRAWAL"
FEE = "FEE"
TRANSACTION_TYPES = (BUY, SELL, DIVIDEND, CONTRIBUTION, WITHDRAWAL, FEE)

SECURITIES_COLUMNS = ("security_id", "security")
PRICES_COLUMNS = ("security_id", "security", "date", "price", "price_label")
ACCOUNTS_COLUMNS = (
    "account_id",
    "account_type",
    "registration",
    "owners",
    "opened",
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
CASH_COLUMNS = ("account_id", "settled_cash", "unsettled_cash", "valuation_date", "known_as_of")


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
    amount: Decimal


@dataclass(frozen=True)
class TaxLotRow:
    line: int
    account_id: str
    lot_id: str
    security_id: str
    units: Decimal
    cost_basis: Decimal
    valuation_date: date


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
            amount=_decimal(path, i, "amount", r["amount"]),
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
            units=_decimal(path, i, "units", r["units"]),
            cost_basis=_decimal(path, i, "cost_basis", r["cost_basis"]),
            valuation_date=_date(path, i, "valuation_date", r["valuation_date"]),
        )
        for i, r in enumerate(read_csv(household_root, path, TAX_LOTS_COLUMNS), start=2)
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
