"""The rules table for a tax year: every parameter with its value and a primary-source citation.

A parameter or table with no citation fails to load, so no figure enters the book unsourced.
"""

import tomllib
from dataclasses import dataclass
from decimal import Decimal
from importlib.resources import files
from typing import Any

from casebook.model.money import MoneyFormatError, parse_decimal


class RulesError(ValueError):
    pass


@dataclass(frozen=True)
class Parameter:
    name: str
    value: Decimal
    citation: str


@dataclass(frozen=True)
class Table:
    name: str
    citation: str
    values: dict[int, Decimal]


@dataclass(frozen=True)
class Rules:
    year: int
    parameters: dict[str, Parameter]
    tables: dict[str, Table]

    def value(self, name: str) -> Decimal:
        if name not in self.parameters:
            raise RulesError(f"no parameter {name!r} in the {self.year} rules")
        return self.parameters[name].value

    def factor(self, table: str, key: int) -> Decimal:
        if table not in self.tables:
            raise RulesError(f"no table {table!r} in the {self.year} rules")
        values = self.tables[table].values
        if key not in values:
            raise RulesError(f"table {table!r} in the {self.year} rules has no entry for {key}")
        return values[key]

    def citation(self, name: str) -> str:
        if name in self.parameters:
            return self.parameters[name].citation
        if name in self.tables:
            return self.tables[name].citation
        raise RulesError(f"no parameter or table {name!r} in the {self.year} rules")


def _decimal(text: Any, where: str) -> Decimal:
    # TOML floats and ints would carry binary rounding or hide a typo, so values are strings only.
    if not isinstance(text, str):
        raise RulesError(f'{where}: value must be a string such as "0.038", not {type(text).__name__} {text!r}')
    try:
        return parse_decimal(text)
    except MoneyFormatError as error:
        raise RulesError(f"{where}: {error}") from error


def _citation(entry: dict[str, Any], where: str) -> str:
    citation = entry.get("citation")
    if citation is None:
        raise RulesError(f"{where}: no citation")
    if not isinstance(citation, str) or not citation.strip():
        raise RulesError(f"{where}: empty citation")
    return citation


def _section(raw: dict[str, Any], key: str, source: str) -> dict[str, Any]:
    section = raw.get(key)
    if not isinstance(section, dict):
        raise RulesError(f"{source}: no [{key}] section")
    return section


def _entry(name: str, entry: Any, where: str) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise RulesError(f"{where}: {name!r} must be a table with a value and a citation")
    return entry


def _parameter(name: str, entry: Any, source: str) -> Parameter:
    where = f"{source}: parameter {name!r}"
    fields = _entry(name, entry, where)
    citation = _citation(fields, where)
    if "value" not in fields:
        raise RulesError(f"{where}: no value")
    return Parameter(name, _decimal(fields["value"], where), citation)


def _table(name: str, entry: Any, source: str) -> Table:
    where = f"{source}: table {name!r}"
    fields = _entry(name, entry, where)
    citation = _citation(fields, where)
    rows = fields.get("values")
    if not isinstance(rows, dict) or not rows:
        raise RulesError(f"{where}: no values")
    values: dict[int, Decimal] = {}
    for key, text in rows.items():
        if not key.isdecimal():
            raise RulesError(f"{where}: key {key!r} is not a whole number")
        values[int(key)] = _decimal(text, f"{where}, entry {key}")
    return Table(name, citation, values)


def parse_rules(raw: dict[str, Any], source: str) -> Rules:
    year = raw.get("year")
    if not isinstance(year, int) or isinstance(year, bool):
        raise RulesError(f"{source}: year must be a whole number, not {year!r}")
    parameters = {name: _parameter(name, entry, source) for name, entry in _section(raw, "parameters", source).items()}
    tables = {name: _table(name, entry, source) for name, entry in _section(raw, "tables", source).items()}
    return Rules(year, parameters, tables)


def load_rules(year: int = 2025) -> Rules:
    filename = f"rules_{year}.toml"
    resource = files("casebook.rules") / filename
    if not resource.is_file():
        raise RulesError(f"no rules table for {year}: {filename} is missing")
    rules = parse_rules(tomllib.loads(resource.read_text(encoding="utf-8")), filename)
    if rules.year != year:
        raise RulesError(f"{filename} says year {rules.year}, not {year}")
    return rules
