"""What follows from the files: the derivations the fabricated-figure rule accepts (the owner's decision of
18 November 2026, option 1 of `docs/decisions/2026-11-18-fabricated-figure-false-zeros.md`).

A number an answer states is fabricated only when it is in no file, the key does not derive it, and it does not
follow from the files in one of these ways:

(a) the arithmetic the answer shows, every operand of which is itself supported;
(b) a sum or difference of values in the files of the cited household (the owner, 18 November 2026: an answer
    often cites one file and adds from two, positions and cash): two values of one record; a field's total over
    the records of one table that share up to two values (an account, a date, a symbol, a quarter of a date); or
    one such total plus or minus another under the same values, in the same file or another; and positions, or
    positions plus cash, summed over any set of the household's accounts on one date (the owner, 19 November 2026:
    a billing group's fee basis, `docs/decisions/2026-11-19-billing-group-totals.md`);
(c) an age from a birth date in the files: a whole number the label calls an age, a year it names (or a year of
    the files' dates) less the year of a date in the cited files, or one less than that;
(d) a count of the households, rows or records at the cited path: a whole number no larger than the files, the
    folders or the rows and records that path holds;
(e) a parameter of the 2025 rules table;
(f) for an amount in prose, a rounding of a figure the answer cites and the rule accepts, or one the key computes,
    to the places the amount is written to: "$1,062" for 1,061.56, "$440k" for 437,776, "$430,000" within
    $5,000 (the owner, 18 November 2026).

A value that is not a number is never a fabricated figure (`graders.common` judges only the amounts written as
money in it). This module computes what (a) to (e) accept; `graders.common.Support` applies them.
"""

import csv
import io
import json
import re
import tomllib
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal, DivisionByZero, InvalidOperation
from functools import cache
from itertools import combinations
from pathlib import Path

from casebook import rules
from casebook.model.files import CASH_CSV, POSITIONS_CSV
from casebook.model.money import CENT, cents

RULES_2025 = Path(rules.__file__ or "").with_name("rules_2025.toml")
# A whole-number operand an answer may write without a file holding it: a percentage's 100, months, quarters,
# "1 - x", "minus 3". Never a figure in its own right.
SMALL_OPERAND = Decimal(100)
MAX_AGE = 130
# The longest run of tokens read as one piece of arithmetic; a longer one is read from its start.
MAX_RUN = 48


@cache
def rules_parameters() -> frozenset[Decimal]:
    """Every parameter of the 2025 rules table (e): the limits, thresholds, rates and ages; not its life-expectancy
    tables, whose hundreds of entries would make every small number a constant."""
    table = tomllib.loads(RULES_2025.read_text(encoding="utf-8"))
    return frozenset(abs(Decimal(str(p["value"]))) for p in table["parameters"].values())


# --- (a) arithmetic shown ------------------------------------------------------------------------------------

_NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
# What reads as a number but names something: an identifier (SYN-46330002, HH-0218, T-4105-0034/35/36, 1099-R,
# 30-day), a date, a quarter, an account type.
_NOT_OPERANDS = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b"
    r"|\b[\w.]*[A-Za-z][\w.]*-[\w./-]+"
    r"|\b\d+-[A-Za-z][\w-]*"
    r"|\b401\s*\(k\)|\b403\s*\(b\)|\b457\s*\(b\)"
    r"|\bQ[1-4]\s+\d{4}\b",
    re.IGNORECASE,
)
# Written with escapes: the multiplication and division signs, the minus sign and the en dash.
_SIGNS = "\u00d7\u00f7\u2212\u2013"
_TOKEN = re.compile(r"(" + _NUMBER + r")(\s*%)?|([-+*/" + _SIGNS + r"])|([()])|([A-Za-z]+)|(\S)")
_WORD_OPERATORS = {"plus": "+", "minus": "-", "less": "-", "times": "*", "x": "*", "over": "/", "divided": "/"}
_OPERATORS = {"+": "+", "-": "-", "\u2212": "-", "\u2013": "-", "*": "*", "\u00d7": "*", "/": "/", "\u00f7": "/"}


@dataclass(frozen=True)
class Expression:
    """Arithmetic an answer shows: its result and the numbers it works on."""

    result: Decimal
    operands: tuple[Decimal, ...]


def _tokens(text: str) -> list[list[str | Decimal]]:
    """The text as runs of numbers, operators and parentheses, split where punctuation ends a run; words between
    two tokens ("positions 2,874,075.28 + cash 183,942.89") are passed over, operator words read as operators."""
    runs: list[list[str | Decimal]] = [[]]
    for match in _TOKEN.finditer(_NOT_OPERANDS.sub(" ", text)):
        number, percent, operator, paren, word, other = match.groups()
        if number is not None:
            value = Decimal(number.replace(",", ""))
            runs[-1].append(value / 100 if percent else value)
        elif operator is not None:
            runs[-1].append(_OPERATORS[operator])
        elif paren is not None:
            runs[-1].append(paren)
        elif word is not None:
            if word.lower() in _WORD_OPERATORS:
                runs[-1].append(_WORD_OPERATORS[word.lower()])
        elif other is not None and other not in "$":
            runs.append([])
    return [r for r in runs if r]


class _Parser:
    """A recursive-descent reading of + - * / and parentheses over Decimal; any other shape is not arithmetic."""

    def __init__(self, tokens: Sequence[str | Decimal]) -> None:
        self.tokens, self.at, self.operands = tokens, 0, list[Decimal]()

    def _peek(self) -> str | Decimal | None:
        return self.tokens[self.at] if self.at < len(self.tokens) else None

    def parse(self) -> Decimal | None:
        try:
            value = self._sum()
        except (ValueError, DivisionByZero, InvalidOperation, ZeroDivisionError):
            return None
        return value if self.at == len(self.tokens) else None

    def _sum(self) -> Decimal:
        value = self._product()
        while self._peek() in ("+", "-"):
            operator = self.tokens[self.at]
            self.at += 1
            right = self._product()
            value = value + right if operator == "+" else value - right
        return value

    def _product(self) -> Decimal:
        value = self._atom()
        while self._peek() in ("*", "/"):
            operator = self.tokens[self.at]
            self.at += 1
            right = self._atom()
            value = value * right if operator == "*" else value / right
        return value

    def _atom(self) -> Decimal:
        token = self._peek()
        self.at += 1
        if isinstance(token, Decimal):
            self.operands.append(token)
            return token
        if token == "(":
            value = self._sum()
            if self._peek() != ")":
                raise ValueError("unclosed parenthesis")
            self.at += 1
            return value
        if token == "-":
            return -self._atom()
        raise ValueError(f"not an operand: {token!r}")


def expressions(text: str) -> list[Expression]:
    """Every piece of arithmetic the text shows: each stretch of a run that parses whole and has an operator."""
    found: list[Expression] = []
    for run in _tokens(text):
        run = run[:MAX_RUN]
        for start in range(len(run)):
            for end in range(len(run), start + 2, -1):
                piece = run[start:end]
                if not any(isinstance(t, str) and t in "+-*/" for t in piece):
                    continue
                parser = _Parser(piece)
                result = parser.parse()
                if result is not None and len(parser.operands) >= 2:
                    found.append(Expression(result, tuple(parser.operands)))
    return found


def shown_precision(value: Decimal) -> Decimal:
    """Half a unit of the last place the value is written to, and never under a cent: 78 is 78 to within 0.5,
    6785.71 to within a cent."""
    exponent = value.as_tuple().exponent  # as written: "1062.00" is to the cent, not to the dollar
    places = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    return max(CENT, Decimal(1).scaleb(-places) / 2)


def matches(value: Decimal, result: Decimal, percent: bool) -> bool:
    """Whether a stated value is a result, to the places the value is written to (a percentage either way)."""
    tolerance = shown_precision(value)
    candidates = (result, result * 100) if percent else (result,)
    return any(abs(abs(value) - abs(c)) <= tolerance for c in candidates)


# --- (b) sums and differences, (d) counts --------------------------------------------------------------------

_DATE = re.compile(r"^(\d{4})-(\d{2})-\d{2}")
_PLAIN_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
# A pseudo-field: which file of a glob a record came from (its household folder, in a whole-book task).
FROM = "@file"
type Record = dict[str, str | Decimal]


def _value(raw: object) -> str | Decimal | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int | Decimal):
        return Decimal(raw)
    if isinstance(raw, str):
        text = raw.strip()
        return Decimal(text) if _PLAIN_NUMBER.fullmatch(text) else text
    return None


def _flat(item: dict[str, object], prefix: str = "") -> Record:
    record: Record = {}
    for name, raw in item.items():
        if isinstance(raw, dict):
            record |= _flat(raw, f"{prefix}{name}.")  # pyright: ignore[reportUnknownArgumentType]
        elif (value := _value(raw)) is not None:
            record[f"{prefix}{name}"] = value
    return record


def _json_tables(node: object, where: str = "") -> Iterator[tuple[str, list[Record]]]:
    """Every list of objects in a JSON tree, by where it sits, each object flattened to its scalar fields."""
    if isinstance(node, list):
        items: list[object] = list(node)  # pyright: ignore[reportUnknownArgumentType]
        if items and all(isinstance(i, dict) for i in items):
            yield where, [_flat(i) for i in items]  # pyright: ignore[reportArgumentType]
        for index, item in enumerate(items):
            yield from _json_tables(item, f"{where}[{index}]" if not isinstance(item, dict) else f"{where}[]")
    elif isinstance(node, dict):
        for name, child in node.items():  # pyright: ignore[reportUnknownVariableType]
            yield from _json_tables(child, f"{where}.{name}")


def file_tables(path: Path) -> list[tuple[str, list[Record]]]:
    """A file's records: a CSV's rows; every list of objects in a JSON file; nothing in any other file."""
    if path.suffix == ".csv":
        rows = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))
        return [("", [{k: v for k, raw in row.items() if (v := _value(raw)) is not None} for row in rows])]
    if path.suffix == ".json":
        tree = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
        merged: dict[str, list[Record]] = {}
        for where, records in _json_tables(tree):
            merged.setdefault(where, []).extend(records)
        return list(merged.items())
    return []


def _keys(record: Record) -> list[tuple[str, str]]:
    """What a record can be grouped by: each value that is not a number, and a date's year, quarter and month."""
    keys: list[tuple[str, str]] = []
    for name, value in record.items():
        if isinstance(value, str):
            keys.append((name, value))
            if date := _DATE.match(value):
                year, month = date.group(1), int(date.group(2))
                keys += [(f"{name}#year", year), (f"{name}#quarter", f"{year}Q{(month - 1) // 3 + 1}")]
                keys.append((f"{name}#month", f"{year}-{month:02d}"))
    return sorted(set(keys))


class Derivations:
    """What (b) accepts over a set of files: the sums and differences of their values, to the cent."""

    def __init__(self, root: Path, files: Iterable[Path]) -> None:
        self.root = root
        self.files = sorted(set(files))
        self._values: set[Decimal] | None = None

    def values(self) -> set[Decimal]:
        if self._values is None:
            self._values = self._compute()
        return self._values

    def _compute(self) -> set[Decimal]:
        values: set[Decimal] = set()
        # One table per kind of file in the set: a glob's files pooled, each record named by its file.
        tables: dict[tuple[str, str], list[Record]] = {}
        for path in self.files:
            relative = path.relative_to(self.root)
            for where, records in file_tables(path):
                tables.setdefault((path.name, where), []).extend({**r, FROM: str(relative.parent)} for r in records)
        # One table's totals are pooled with every other table's under the same values: positions and cash on
        # one date, in one file or two.
        by_values: dict[tuple[str, ...], list[Decimal]] = {}
        for records in tables.values():
            totals: dict[tuple[tuple[str, str], ...], dict[str, Decimal]] = {}
            for record in records:
                numbers = {k: v for k, v in record.items() if isinstance(v, Decimal)}
                for a, b in combinations(numbers.values(), 2):
                    values.update((abs(a + b), abs(a - b)))
                keys = _keys(record)
                for group in [(), *((k,) for k in keys), *combinations(keys, 2)]:
                    bucket = totals.setdefault(group, {})
                    for name, number in numbers.items():
                        bucket[name] = bucket.get(name, Decimal(0)) + number
            for group, bucket in totals.items():
                by_values.setdefault(tuple(sorted(v for _, v in group)), []).extend(bucket.values())
        for numbers in by_values.values():
            values.update(abs(n) for n in numbers)
            for a, b in combinations(numbers, 2):
                values.update((abs(a + b), abs(a - b)))
        for home in sorted({p.parents[1] for p in self.files if p.as_posix().endswith(POSITIONS_CSV)}):
            values |= account_totals(home)
        return {cents(v) for v in values}

    def has(self, value: Decimal) -> bool:
        """A sum or difference (b), to the cent."""
        target = cents(abs(value))
        found = self.values()
        return any(target + step in found for step in (Decimal(0), CENT, -CENT))


def _account_sums(path: Path, fields: Sequence[str]) -> dict[tuple[str, str], Decimal]:
    """A custodian file's money by date and account, the given fields summed; a row lacking one is not counted
    (the files are read as the rest of (b) reads them, never refused)."""
    sums: dict[tuple[str, str], Decimal] = {}
    for _, records in file_tables(path) if path.is_file() else []:
        for record in records:
            day, account = record.get("valuation_date"), record.get("account_id")
            numbers = [record.get(f) for f in fields]
            if isinstance(day, str) and isinstance(account, str) and all(isinstance(n, Decimal) for n in numbers):
                key = (day, account)
                sums[key] = sums.get(key, Decimal(0)) + sum((n for n in numbers if isinstance(n, Decimal)), Decimal(0))
    return sums


def account_totals(home: Path) -> set[Decimal]:
    """A household's positions, and its positions plus cash, summed over each set of its accounts on each date: a
    billing group's quarter-end value is one (the owner, 19 November 2026)."""
    held = _account_sums(home / POSITIONS_CSV, ("market_value",))
    cash = _account_sums(home / CASH_CSV, ("settled_cash", "unsettled_cash"))
    totals: set[Decimal] = set()
    for day in sorted({d for d, _ in held}):
        accounts = sorted(a for d, a in held if d == day)
        for size in range(1, len(accounts) + 1):
            for chosen in combinations(accounts, size):
                positions = sum((held[(day, a)] for a in chosen), Decimal(0))
                totals |= {positions, positions + sum((cash.get((day, a), Decimal(0)) for a in chosen), Decimal(0))}
    return totals


@dataclass(frozen=True)
class Cited:
    """What a cited source names: its files and folders, and the files of the household (or households) they
    belong to, over which (b) adds."""

    files: tuple[Path, ...]
    folders: int
    household: tuple[Path, ...]

    def records(self) -> int:
        """The most there is to count at the cited path (d): its files, its folders, or its rows and records."""
        rows = sum(len(records) for path in self.files for _, records in file_tables(path))
        return max(len(self.files), self.folders, rows)


HOUSEHOLDS = "households"


def household_files(root: Path, files: Iterable[Path]) -> tuple[Path, ...]:
    """The files of the households the given files belong to: in a whole-book task each household's folder
    (`households/<ID>/`), in a one-household task the whole fixture."""
    homes: set[Path] = set()
    for path in files:
        parts = path.relative_to(root).parts
        homes.add(root / parts[0] / parts[1] if parts[0] == HOUSEHOLDS and len(parts) > 2 else root)
    return tuple(sorted({p for home in homes for p in home.rglob("*") if p.is_file()}))


_PLACEHOLDER = re.compile(r"<[^<>/]+>")


def resolve(root: Path, source: str) -> Cited | None:
    """What a cited source names: one or more paths or globs ("a; b", "a, b", "a vs b"), each inside the
    fixtures, a placeholder such as `<household ID>` read as any folder. None when no part names anything there."""
    files: list[Path] = []
    folders = 0
    named = False
    for part in re.split(r"\s*(?:;|,|\bvs\.?|\band\b|\s\+\s)\s*", source):
        part = _PLACEHOLDER.sub("*", part.strip().strip("`'\""))
        if not part or part.startswith(("/", "..")):
            continue
        matched = list(root.glob(part.rstrip("/"))) if any(c in part for c in "*?[") else [root / part.rstrip("/")]
        for path in matched:
            path = path.resolve()
            if not path.is_relative_to(root) or not path.exists():
                continue
            named = True
            if path.is_dir():
                children = list(path.iterdir())
                folders += sum(c.is_dir() for c in children) if len(matched) == 1 else 1
                files += [p for p in path.rglob("*") if p.is_file()]
            else:
                files.append(path)
    return Cited(tuple(sorted(set(files))), folders, household_files(root, files)) if named else None


# --- (c) ages --------------------------------------------------------------------------------------------------

_AGE = re.compile(r"\bage[ds]?\b", re.IGNORECASE)
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_DATES = re.compile(r"(?<!\d)((?:19|20)\d{2})-\d{2}-\d{2}(?!\d)")


def is_age(label: str, value: Decimal, texts: Callable[[], Iterable[str]]) -> bool:
    """(c): a whole number the label calls an age, the year it names (or a year of the files' dates) less the year
    of a date in the cited files, or one less (the birthday not yet reached)."""
    if not _AGE.search(label) or value != value.to_integral_value() or not 0 < value < MAX_AGE:
        return False
    born = {int(y) for text in texts() for y in _DATES.findall(text)}
    at = {int(y) for y in _YEAR.findall(label)} or {y for y in born if y >= 2000}
    return any(int(value) in (year - birth, year - birth - 1) for year in at for birth in born)


def is_count(value: Decimal, records: int) -> bool:
    """(d): a whole number no larger than what the cited path holds."""
    return value == value.to_integral_value() and 0 <= value <= records


# --- (f) rounding --------------------------------------------------------------------------------------------

_WRITTEN = re.compile(r"(" + _NUMBER + r")\s*(thousand|million|billion|mn|bn|k|m)?\b", re.IGNORECASE)
_SCALES = {"thousand": 3, "k": 3, "million": 6, "m": 6, "mn": 6, "billion": 9, "bn": 9}


def rounding_unit(words: str) -> Decimal | None:
    """The unit an amount in prose is rounded to, from how it is written: "$440k" to ten thousand, "$187.5k" to a
    hundred, "$430,000" to ten thousand, "$1,062" to a dollar, "$1,061.6" to a dime; None for one written to the
    cent, which is exact."""
    match = _WRITTEN.search(words)
    if match is None:
        return None
    number, scale = match.group(1).replace(",", ""), _SCALES.get((match.group(2) or "").lower(), 0)
    whole, _, decimals = number.partition(".")
    if decimals:
        # "$187.5k" to a hundred, "$1,061.6" to a dime; written to the cent (or finer) it is exact.
        return None if not scale and len(decimals) >= 2 else Decimal(1).scaleb(scale - len(decimals))
    zeros = len(whole) - len(whole.rstrip("0")) if whole.strip("0") else 0
    return Decimal(1).scaleb(scale + zeros)


def rounds(value: Decimal, unit: Decimal, figures: Iterable[Decimal]) -> bool:
    """(f): the amount is one of the figures rounded to its unit."""
    return any(abs(abs(value) - abs(f)) <= unit / 2 for f in figures)
