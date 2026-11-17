"""What every grader shares: reading an answer's closing json block, the score and its breakdown, the three
counts, and the fabricated-figure rule.

A figure the answer cites must appear in the source file it names inside the fixtures, or sit within a
dollar of a figure the key computes (marked computed or not: a true figure is not fabricated for want of
the flag). A figure given as text, such as a date, must appear in its source as written, or every number
in it must be supported that way. The answer's headline amounts, and every amount anywhere in the answer
stated as money, prose included, must appear in some fixture file or sit within a dollar of a key figure.
The key lists the figures its task invites an answer to derive; a derivation it does not list counts as
fabricated. A fabricated figure is a critical fail: the score is zero and the breakdown is kept.
"""

import csv
import io
import json
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from casebook.model.money import MoneyFormatError, fmt, parse_decimal

logging.getLogger("pypdf").setLevel(logging.ERROR)

PASS_SCORE = 70
TOLERANCE = Decimal("1.00")
FIGURE_FIELDS = ("label", "value", "source")
OUTPUT_PARSES = "output_parses"
# The three counts every result records (docs/SPEC.md): a correct "unresolved", an unnecessary refusal, a
# false alarm.
CORRECT_UNRESOLVED, UNNECESSARY_REFUSAL, FALSE_ALARM = "correct_unresolved", "unnecessary_refusal", "false_alarm"
COUNTS = (CORRECT_UNRESOLVED, UNNECESSARY_REFUSAL, FALSE_ALARM)
UNRESOLVED = "unresolved"

_JSON_BLOCK = re.compile(r"```json[ \t]*\n(.*?)```", re.DOTALL)
# A grouped number (1,234.56) or a plain one (1234.56); the sign is left off on purpose.
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
# An amount in prose: marked as money ($, US$, USD, dollars, optionally with a multiplier), or
# written as money is (grouped thousands, or exactly two decimals). A percentage is a rate, not one.
_FIGURE = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_SCALE = {"thousand": 3, "k": 3, "million": 6, "m": 6, "mn": 6, "billion": 9, "bn": 9}
_SCALE_WORDS = r"(?:\s*(thousand|million|billion|mn|bn|k|m)\b)?"
_AMOUNT = re.compile(
    r"(?:US\$|\$|\bUSD\s?)\s?("
    + _FIGURE
    + r")"
    + _SCALE_WORDS
    + r"|("
    + _FIGURE
    + r")"
    + _SCALE_WORDS
    + r"\s*(?:dollars|USD)\b"
    + r"|(?<![\d.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d{2})(?![\d%]|\.\d)",
    re.IGNORECASE,
)


def prose_amounts(text: str) -> list[tuple[str, Decimal]]:
    """Every amount the text states as money, scaled by any multiplier, with the words that state it."""
    found: list[tuple[str, Decimal]] = []
    for match in _AMOUNT.finditer(text):
        number = match.group(1) or match.group(3) or match.group(5)
        scale = (match.group(2) or match.group(4) or "").lower()
        value = parse_decimal(number.replace(",", "")) * (Decimal(10) ** _SCALE.get(scale, 0))
        found.append((match.group(0).strip(), value))
    return found


@dataclass(frozen=True)
class Criterion:
    name: str
    points: int
    earned: int
    detail: str


@dataclass(frozen=True)
class Grade:
    score: int
    breakdown: tuple[Criterion, ...]
    critical_fail: str | None
    counts: dict[str, int]
    # The criteria a pass cannot do without, whatever the score (the finding, and the amount it turns on).
    essential: frozenset[str] = field(default=frozenset())

    @property
    def passed(self) -> bool:
        """A pass needs the score, no critical fail, and every essential criterion met in full."""
        essential = all(c.earned == c.points for c in self.breakdown if c.name in self.essential)
        return self.score >= PASS_SCORE and self.critical_fail is None and essential

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "passed": self.passed,
            "critical_fail": self.critical_fail,
            "counts": dict(self.counts),
            "breakdown": [
                {"name": c.name, "points": c.points, "earned": c.earned, "detail": c.detail} for c in self.breakdown
            ],
        }


def _earned(name: str, points: int, met: bool | int) -> int:
    if isinstance(met, bool):
        return points if met else 0
    if not 0 <= met <= points:
        raise ValueError(f"criterion {name} earns {met} of {points} points")
    return met


def grade_from(
    results: Iterable[tuple[str, int, bool | int, str]],
    critical: str | None,
    counts: dict[str, int],
    essential: Iterable[str],
) -> Grade:
    """A grade from each criterion's name, points, whether it was met (or the points it earned, for one scored
    in part, such as tone), and why; zero on a critical fail."""
    if set(counts) != set(COUNTS):
        raise ValueError(f"a result records exactly the three counts {', '.join(COUNTS)}, not {sorted(counts)}")
    breakdown = tuple(
        Criterion(name, points, _earned(name, points, met), detail) for name, points, met, detail in results
    )
    score = 0 if critical else sum(c.earned for c in breakdown)
    return Grade(score, breakdown, critical, dict(counts), frozenset(essential))


def counts_for(found: str | None, expected: str, alarm: Iterable[str], clean: Iterable[str]) -> dict[str, int]:
    """The three counts, from the answer's finding and the key's: "unresolved" is correct only where the key
    says so; a refusal where the key settles the question is unnecessary; a finding in `alarm` where the key
    finds one of `clean` is a false alarm."""
    return {
        CORRECT_UNRESOLVED: int(found == UNRESOLVED and expected == UNRESOLVED),
        UNNECESSARY_REFUSAL: int(found == UNRESOLVED and expected != UNRESOLVED),
        FALSE_ALARM: int(found in set(alarm) and expected in set(clean)),
    }


@dataclass(frozen=True)
class Figure:
    label: str
    value: Decimal | None
    text: str
    source: str
    computed: bool

    @property
    def shown(self) -> str:
        return self.text if self.value is None else fmt(self.value)


class NotMoney(ValueError):
    pass


def money(value: object) -> Decimal | None:
    """An amount from the answer's json: a number, or text such as "$1,234.56"; None for null."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise NotMoney(repr(value))
    if isinstance(value, int | Decimal):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return parse_decimal(value.replace("$", "").replace(",", "").strip())
        except MoneyFormatError as error:
            raise NotMoney(repr(value)) from error
    raise NotMoney(repr(value))


def json_block(output_text: str) -> dict[str, Any] | str:
    """The last fenced json block as an object, or why there is none."""
    blocks = _JSON_BLOCK.findall(output_text)
    if not blocks:
        return "no fenced json block"
    try:
        data = json.loads(blocks[-1], parse_float=Decimal)
    except json.JSONDecodeError as error:
        return f"the json block is not JSON ({error})"
    if not isinstance(data, dict):
        return "the json block is not an object"
    return data


def figures(raw: object, problems: list[str]) -> tuple[Figure, ...]:
    """The answer's "figures" list; each malformed entry adds a problem and is left out."""
    if not isinstance(raw, list):
        problems.append("figures is not a list")
        return ()
    found: list[Figure] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or any(f not in item for f in FIGURE_FIELDS):
            problems.append(f"figures[{index}] lacks one of {', '.join(FIGURE_FIELDS)}")
            continue
        raw_value = item["value"]
        try:
            value = money(raw_value)
        except NotMoney:
            value = None
        text = raw_value.strip() if isinstance(raw_value, str) else ""
        if value is None and not text:
            problems.append(f"figures[{index}] value {raw_value!r} is neither a number nor text")
            continue
        found.append(Figure(str(item["label"]), value, text, str(item["source"]), item.get("computed") is True))
    return tuple(found)


def close(value: Decimal | None, expected: Decimal) -> bool:
    return value is not None and abs(value - expected) <= TOLERANCE


def file_text(path: Path) -> str:
    if path.suffix == ".pdf":
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".csv":
        # One cell per line, so the comma between two cells never reads as a thousands separator.
        return "\n".join(cell for row in csv.reader(io.StringIO(text)) for cell in row)
    return text


def _numbers(text: str) -> set[Decimal]:
    return {parse_decimal(m.replace(",", "")) for m in _NUMBER.findall(text)}


# A life-expectancy factor or period is read from the IRS's tables, not from the fixtures: cited with this
# source, it is accepted when it is one the key itself uses.
TABLE_SOURCE = "IRS Publication 590-B"


def file_figures(cited: Sequence[Figure], table: Sequence[Decimal]) -> tuple[Figure, ...]:
    """The cited figures the fabricated-figure rule judges: all but the table lookups the key uses."""
    return tuple(f for f in cited if not (f.source == TABLE_SOURCE and f.value is not None and f.value in table))


# A price is read, never derived: no key computes one, so a figure the answer calls a price, or an amount
# its prose writes as one ("priced at $98.50", "bought at $98.50 a share"), must be in the fixtures
# themselves. A per-unit loss or dividend is not a price.
_PRICE_LABEL = re.compile(r"\bprice[sd]?\b", re.IGNORECASE)
_PROSE_PRICE = re.compile(
    r"\bat\s+\$\s?(\d[\d,]*(?:\.\d+)?)\s+(?:a|per|each)\s+(?:share|unit)\b"
    r"|\b(?:price[sd]?|priced)(?:(?:\s+(?:of|was|were|is|at)|\s*[=:])\s*){1,2}\$\s?(\d[\d,]*(?:\.\d+)?)",
    re.IGNORECASE,
)
# An amount written as money: a table factor is a number, never one.
_AS_MONEY = re.compile(r"\$|\bUSD\b|dollars", re.IGNORECASE)


class Support:
    """Whether a figure is in the fixtures or follows from the key: the fabricated-figure rule.

    `table` holds the IRS table lookups the key itself uses (life-expectancy factors), which an answer may
    state anywhere, in any decimal form."""

    def __init__(self, fixtures: Path, computed: Sequence[Decimal], table: Sequence[Decimal] = ()) -> None:
        self.root = fixtures.resolve()
        self.computed = tuple(abs(v) for v in computed)
        self.table = frozenset(table)
        self._numbers: dict[Path, set[Decimal]] = {}
        self._texts: dict[Path, str] = {}

    def _text(self, path: Path) -> str:
        if path not in self._texts:
            self._texts[path] = file_text(path)
        return self._texts[path]

    def _numbers_in(self, path: Path) -> set[Decimal]:
        if path not in self._numbers:
            self._numbers[path] = _numbers(self._text(path))
        return self._numbers[path]

    def _from_key(self, value: Decimal) -> bool:
        return any(close(abs(value), c) for c in self.computed)

    def in_files(self, value: Decimal) -> bool:
        return any(
            abs(value) in self._numbers_in(path) for path in sorted(p for p in self.root.rglob("*") if p.is_file())
        )

    def fabricated(self, figure: Figure) -> bool:
        path = (self.root / figure.source).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            return True
        if figure.value is None:
            # Text, such as a date or several amounts in one: as written in the source, or every number in it supported.
            if figure.text in self._text(path):
                return False
            numbers = [parse_decimal(n.replace(",", "")) for n in _NUMBER.findall(figure.text)]
            price = bool(_PRICE_LABEL.search(figure.label))
            return not numbers or not all(
                n in self._numbers_in(path) or (not price and self._from_key(n)) for n in numbers
            )
        if abs(figure.value) in self._numbers_in(path):
            return False
        if _PRICE_LABEL.search(figure.label):
            return True  # a price no file holds is not made good by a key figure of the same size
        return not self._from_key(figure.value)

    def anywhere(self, value: Decimal, as_money: bool = True) -> bool:
        """Whether an amount is in the fixtures or follows from the key; a table factor counts only where
        the amount is not written as money (`as_money` false)."""
        if value == 0:  # "nothing owed" claims no figure
            return True
        if self._from_key(value) or (not as_money and abs(value) in self.table):
            return True
        return self.in_files(value)

    def first_fabrication(
        self, output_text: str, cited: Sequence[Figure], headline: Sequence[tuple[str, Decimal | None]]
    ) -> str | None:
        """The first figure the answer cites, states as a headline amount, or writes as money in prose that
        is in no file and follows from none."""
        for figure in cited:
            if self.fabricated(figure):
                return f"fabricated figure: {figure.label} = {figure.shown} (cited {figure.source})"
        for name, value in headline:
            if value is not None and not self.anywhere(value):
                return f"fabricated figure: {name} = {fmt(value)} is in no file and follows from none"
        for match in _PROSE_PRICE.finditer(output_text):
            price = parse_decimal((match.group(1) or match.group(2)).replace(",", ""))
            if not self.in_files(price):
                return f"fabricated figure: the price {match.group(0).strip()!r} in the answer is in no file"
        for words, value in prose_amounts(output_text):
            if not self.anywhere(value, as_money=bool(_AS_MONEY.search(words))):
                return f"fabricated figure: {words!r} in the answer is in no file and follows from none"
        return None
