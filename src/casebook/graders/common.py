"""What every grader shares: reading an answer's closing json block, the score and its breakdown, the three
counts, and the fabricated-figure rule.

A number the answer cites, states as a headline amount, or writes as money anywhere, prose included, is
fabricated only when it is in no fixture file, is not within a dollar of a figure the key computes (marked
computed or not), and does not follow from the files in one of the ways `graders.derivations` names: arithmetic
the answer shows, a sum or difference over the cited household's files, an age from a birth date, a count of
what the cited path holds, a parameter of the rules table, or, for an amount in prose, a rounding of a figure
the answer cites or the key computes (the owner's decision of 18 November 2026,
`docs/decisions/2026-11-18-fabricated-figure-false-zeros.md`). A cited number must be in the file it names, or
follow so. A price is read, never derived. A value that is not a number is never a fabricated figure; an amount
written as money inside one is judged as an amount in prose. A fabricated figure is a critical fail: the score
is zero and the breakdown is kept.
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

from casebook.graders.derivations import (
    SMALL_OPERAND,
    Cited,
    Derivations,
    Expression,
    expressions,
    is_age,
    is_count,
    matches,
    resolve,
    rounding_unit,
    rounds,
    rules_parameters,
)
from casebook.model.money import CENT, MoneyFormatError, fmt, parse_decimal

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
# An amount in prose: marked as money ($, US$, USD, dollars, optionally with a multiplier), written as money
# is (grouped thousands, or exactly two decimals), or a number with a multiplier word. A percentage is a rate.
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
    + r"|(?<![\d.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d{2})(?![\d%]|\.\d)"
    # A bare number with a multiplier word, "48 thousand", "50 million" (the owner's fabricated-figure rule,
    # option 1, 18 November 2026). Only the words: "401k" is an account type, "5m" anything.
    + r"|(?<![\d.,])("
    + _FIGURE
    + r")\s*(thousand|million|billion)\b",
    re.IGNORECASE,
)


def prose_amounts(text: str) -> list[tuple[str, Decimal]]:
    """Every amount the text states as money, scaled by any multiplier, with the words that state it."""
    found: list[tuple[str, Decimal]] = []
    for match in _AMOUNT.finditer(text):
        number = match.group(1) or match.group(3) or match.group(5) or match.group(6)
        scale = (match.group(2) or match.group(4) or match.group(7) or "").lower()
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
    """Whether a figure is in the fixtures or follows from them or from the key: the fabricated-figure rule.

    `table` holds the IRS table lookups the key itself uses (life-expectancy factors), which an answer may
    state anywhere, in any decimal form. What follows from the files is `graders.derivations`' (a) to (e)."""

    def __init__(self, fixtures: Path, computed: Sequence[Decimal], table: Sequence[Decimal] = ()) -> None:
        self.root = fixtures.resolve()
        self.computed = tuple(abs(v) for v in computed)
        self.table = frozenset(abs(v) for v in table)
        self._numbers: dict[Path, set[Decimal]] = {}
        self._texts: dict[Path, str] = {}
        self._cited: dict[str, Cited | None] = {}
        self._pools: dict[tuple[Path, ...], Derivations] = {}
        self._files: list[Path] | None = None

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
        if self._files is None:
            self._files = sorted(p for p in self.root.rglob("*") if p.is_file())
        return any(abs(value) in self._numbers_in(path) for path in self._files)

    def cited(self, source: str) -> Cited | None:
        """What a cited source names; None when it names nothing in the fixtures."""
        if source not in self._cited:
            self._cited[source] = resolve(self.root, source)
        return self._cited[source]

    def pool(self, files: Iterable[Path]) -> Derivations:
        """The sums and differences (b) over a household's files, computed once per set of files."""
        key = tuple(sorted(set(files)))
        if key not in self._pools:
            self._pools[key] = Derivations(self.root, key)
        return self._pools[key]

    def _constant(self, value: Decimal, as_money: bool = False) -> bool:
        """The key's figures, the table factors it uses (where the amount is not written as money), and the
        rules table's parameters (e)."""
        number = abs(value)
        return self._from_key(number) or (not as_money and number in self.table) or number in rules_parameters()

    def _operand(self, value: Decimal, context: "_Context", pool: Derivations | None) -> bool:
        """An operand of arithmetic shown (a): supported itself, or a small whole number (100, 12, 4, 1)."""
        number = abs(value)
        if number == 0 or (number <= SMALL_OPERAND and number == number.to_integral_value()):
            return True
        if self._constant(number) or context.accepts(number) or self.in_files(number):
            return True
        return pool is not None and pool.has(number)

    def _shown(
        self, shown: Iterable[Expression], value: Decimal, percent: bool, context: "_Context", pool: Derivations | None
    ) -> bool:
        return any(
            matches(value, e.result, percent) and all(self._operand(o, context, pool) for o in e.operands)
            for e in shown
        )

    def fabricated(self, figure: Figure, context: "_Context | None" = None) -> bool:
        """Whether a cited figure is in no file and follows from neither the key nor the files: a text value is
        judged by the amounts it writes as money, a number by its cited files, the key and (a) to (e)."""
        context = context or _Context()
        cited = self.cited(figure.source)
        if figure.value is None:
            return self._text_fabricated(figure, cited, context)
        value = figure.value
        if value == 0:  # "nothing found" claims no figure
            return False
        if cited is None:
            return True
        if any(abs(value) in self._numbers_in(path) for path in cited.files):
            return False
        if _PRICE_LABEL.search(figure.label):
            return True  # a price is read, never derived: a key figure or a sum of the same size does not make it good
        if self._constant(value) or context.accepts(value):
            return False
        pool = self.pool(cited.household)
        percent = bool(_PERCENT.search(figure.label))
        shown = [*expressions(figure.label), *context.shown]  # its own label's working, or the answer's
        if self._shown(shown, value, percent, context, pool) or pool.has(value):
            return False
        if is_age(figure.label, value, lambda: (self._text(p) for p in cited.files)):
            return False
        return not is_count(value, cited.records())

    def _text_fabricated(self, figure: Figure, cited: Cited | None, context: "_Context") -> bool:
        amounts = prose_amounts(figure.text)
        if _PRICE_LABEL.search(figure.label) and amounts:
            # A price is read, never derived: each amount a price's text writes as money must be in its cited file.
            # Text with none ("not available", a date the price was last reviewed) is no figure (reviewer A, round 2).
            if cited is None:
                return True
            return not all(any(abs(v) in self._numbers_in(p) for p in cited.files) for _, v in amounts)
        # Any other text is no figure, but an amount it writes as money is one, judged as an amount in prose.
        shown = [*expressions(f"{figure.label} {figure.text}"), *context.shown]
        pool = self.pool(cited.household) if cited else context.pool
        return any(
            not self.anywhere(value, bool(_AS_MONEY.search(words)), context, pool, shown, words)
            for words, value in prose_amounts(figure.text)
        )

    def anywhere(
        self,
        value: Decimal,
        as_money: bool = True,
        context: "_Context | None" = None,
        pool: Derivations | None = None,
        shown: Sequence[Expression] = (),
        words: str = "",
    ) -> bool:
        """Whether an amount is in the fixtures, follows from the key, or follows from the files: equal to a
        cited figure the rule accepts, a sum or difference over the cited households' files, arithmetic shown,
        or, for an amount in prose (its `words`), a rounding of a figure the answer cites or the key computes (f).
        A table factor counts only where the amount is not written as money (`as_money` false)."""
        context = context or _Context()
        if value == 0:  # "nothing owed" claims no figure
            return True
        if self._constant(value, as_money) or context.accepts(value) or self.in_files(value):
            return True
        if pool is not None and pool.has(value):
            return True
        if self._shown(shown, value, False, context, pool):
            return True
        unit = rounding_unit(words) if words else None
        return unit is not None and rounds(value, unit, (*self.computed, *context.accepted))

    def _context(self, cited: Sequence[Figure], shown: Sequence[Expression] = ()) -> "_Context":
        """The answer's cited figures the rule accepts, settled until none more is (one may stand on another,
        "(380,605.02 + 207,075.11) = 587680.13"), the sums and counts over every file the answer cites, and the
        arithmetic the answer shows anywhere, which a cited figure may stand on as well as its own label's."""
        context = _Context(shown=tuple(shown))
        named = [c for f in cited if (c := self.cited(f.source)) is not None]
        context.pool = self.pool(p for c in named for p in c.household) if named else None
        settled = False
        while not settled:
            settled = True
            for figure in cited:
                pending = figure.value is not None and figure.value not in context.accepted
                if pending and figure.value is not None and not self.fabricated(figure, context):
                    context.accepted.add(figure.value)
                    settled = False
        return context

    def first_fabrication(
        self,
        output_text: str,
        cited: Sequence[Figure],
        headline: Sequence[tuple[str, Decimal | None]],
        answer: tuple[str, Sequence[Figure]] | None = None,
    ) -> str | None:
        """The first figure the answer cites, states as a headline amount, or writes as money in prose that
        is in no file and follows from none. `answer`, the answer's text and cited figures, when the text judged
        is not the answer's own (a CRM note the run wrote), which may repeat what the answer derived."""
        context_text, context_figures = answer or (output_text, cited)
        shown = expressions(context_text) + (expressions(output_text) if answer else [])
        context = self._context(context_figures, shown)
        for figure in cited:
            if self.fabricated(figure, context):
                return f"fabricated figure: {figure.label} = {figure.shown} (cited {figure.source})"
        for name, value in headline:
            if value is not None and not self.anywhere(value, True, context, context.pool, shown):
                return f"fabricated figure: {name} = {fmt(value)} is in no file and follows from none"
        for match in _PROSE_PRICE.finditer(output_text):
            price = parse_decimal((match.group(1) or match.group(2)).replace(",", ""))
            if not self.in_files(price):
                return f"fabricated figure: the price {match.group(0).strip()!r} in the answer is in no file"
        for words, value in prose_amounts(output_text):
            as_money = bool(_AS_MONEY.search(words))
            if not self.anywhere(value, as_money, context, context.pool, shown, words):
                return f"fabricated figure: {words!r} in the answer is in no file and follows from none"
        return None


_PERCENT = re.compile(r"%|\bper\s?cent\b", re.IGNORECASE)


@dataclass
class _Context:
    """What an answer has already shown to follow: the values of its cited figures the rule accepts, and the
    sums and counts over every file it cites (for an amount in prose or a headline amount, which cites none)."""

    accepted: set[Decimal] = field(default_factory=set[Decimal])
    pool: Derivations | None = None
    shown: tuple[Expression, ...] = ()

    def accepts(self, value: Decimal) -> bool:
        return any(abs(abs(value) - abs(a)) <= CENT for a in self.accepted)
