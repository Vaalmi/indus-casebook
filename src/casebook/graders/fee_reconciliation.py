"""The grader for a fee reconciliation task: scores an answer's closing json block against the fee key.

A figure the answer cites must appear in the source file it names inside the fixtures, or sit
within a dollar of a figure the key computes (marked computed or not: a true figure is not
fabricated for want of the flag). A figure given as text, such as a date, must appear in its
source as written, or every number in it must be supported that way. The answer's three money
fields, and every amount anywhere in the answer stated as money, prose included, must appear in
some fixture file or sit within a dollar of a key figure. The key lists the figures this task
invites an answer to derive; a derivation it does not list counts as fabricated. A fabricated
figure is a critical fail: the score is zero and the breakdown is kept.
"""

import csv
import io
import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from casebook.keys.fee_reconciliation import FeeKey
from casebook.model.money import MoneyFormatError, fmt, parse_decimal

logging.getLogger("pypdf").setLevel(logging.ERROR)

FINDINGS = ("fee_error", "no_fee_error", "unresolved")
REQUIRED_FIELDS = ("finding", "debited_fee", "correct_fee", "amount_misbilled", "figures", "explanation")
FIGURE_FIELDS = ("label", "value", "source")
PASS_SCORE = 70
TOLERANCE = Decimal("1.00")

OUTPUT_PARSES = "output_parses"
FINDING = "finding"
AMOUNT = "amount"
FEES = "fees"
POINTS = {OUTPUT_PARSES: 10, FINDING: 40, AMOUNT: 30, FEES: 20}

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

    @property
    def passed(self) -> bool:
        """A pass needs the score, no critical fail, and both the finding and the amount right."""
        essential = all(c.earned == c.points for c in self.breakdown if c.name in (FINDING, AMOUNT))
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


@dataclass(frozen=True)
class _Figure:
    label: str
    value: Decimal | None
    text: str
    source: str
    computed: bool

    @property
    def shown(self) -> str:
        return self.text if self.value is None else fmt(self.value)


@dataclass(frozen=True)
class _Answer:
    """What could be read from the json block; None where a field is absent or malformed."""

    finding: str | None
    debited_fee: Decimal | None
    correct_fee: Decimal | None
    amount_misbilled: Decimal | None
    figures: tuple[_Figure, ...]
    problems: tuple[str, ...]
    well_formed: frozenset[str]


class _NotMoney(ValueError):
    pass


def _money(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise _NotMoney(repr(value))
    if isinstance(value, int | Decimal):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return parse_decimal(value.replace("$", "").replace(",", "").strip())
        except MoneyFormatError as error:
            raise _NotMoney(repr(value)) from error
    raise _NotMoney(repr(value))


def _json_block(output_text: str) -> dict[str, Any] | str:
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


def _figures(raw: object, problems: list[str]) -> tuple[_Figure, ...]:
    if not isinstance(raw, list):
        problems.append("figures is not a list")
        return ()
    figures: list[_Figure] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or any(f not in item for f in FIGURE_FIELDS):
            problems.append(f"figures[{index}] lacks one of {', '.join(FIGURE_FIELDS)}")
            continue
        raw_value = item["value"]
        try:
            value = _money(raw_value)
        except _NotMoney:
            value = None
        text = raw_value.strip() if isinstance(raw_value, str) else ""
        if value is None and not text:
            problems.append(f"figures[{index}] value {raw_value!r} is neither a number nor text")
            continue
        figures.append(_Figure(str(item["label"]), value, text, str(item["source"]), item.get("computed") is True))
    return tuple(figures)


def _answer(output_text: str) -> _Answer:
    data = _json_block(output_text)
    if isinstance(data, str):
        return _Answer(None, None, None, None, (), (data,), frozenset())
    problems = [f"lacks {name}" for name in REQUIRED_FIELDS if name not in data]
    finding = data.get("finding")
    if "finding" in data and finding not in FINDINGS:
        problems.append(f"finding {finding!r} is not one of {', '.join(FINDINGS)}")
        finding = None
    well_formed = {name for name in REQUIRED_FIELDS if name in data}
    amounts: dict[str, Decimal | None] = {}
    for name in ("debited_fee", "correct_fee", "amount_misbilled"):
        try:
            amounts[name] = _money(data.get(name))
        except _NotMoney:
            problems.append(f"{name} {data[name]!r} is not money")
            well_formed.discard(name)
            amounts[name] = None
    if "explanation" in data and not isinstance(data["explanation"], str):
        problems.append("explanation is not text")
    figures = _figures(data["figures"], problems) if "figures" in data else ()
    return _Answer(
        finding=str(finding) if finding is not None else None,
        debited_fee=amounts["debited_fee"],
        correct_fee=amounts["correct_fee"],
        amount_misbilled=amounts["amount_misbilled"],
        figures=figures,
        problems=tuple(problems),
        well_formed=frozenset(well_formed),
    )


def _close(value: Decimal | None, expected: Decimal) -> bool:
    return value is not None and abs(value - expected) <= TOLERANCE


def _text(path: Path) -> str:
    if path.suffix == ".pdf":
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".csv":
        # One cell per line, so the comma between two cells never reads as a thousands separator.
        return "\n".join(cell for row in csv.reader(io.StringIO(text)) for cell in row)
    return text


def _numbers(text: str) -> set[Decimal]:
    return {parse_decimal(m.replace(",", "")) for m in _NUMBER.findall(text)}


def _fabricated(figure: _Figure, key: FeeKey, fixtures: Path, cache: dict[Path, set[Decimal]]) -> bool:
    root = fixtures.resolve()
    path = (root / figure.source).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return True
    if path not in cache:
        cache[path] = _numbers(_text(path))
    if figure.value is None:
        # Text, such as a date or several amounts in one: as written in the source, or every number in it supported.
        if figure.text in _text(path):
            return False
        numbers = [parse_decimal(n.replace(",", "")) for n in _NUMBER.findall(figure.text)]
        return not numbers or not all(
            n in cache[path] or any(_close(n, abs(f.value)) for f in key.computed_figures) for n in numbers
        )
    if abs(figure.value) in cache[path]:
        return False
    return not any(_close(abs(figure.value), abs(f.value)) for f in key.computed_figures)


def _supported_anywhere(value: Decimal, key: FeeKey, fixtures: Path, cache: dict[Path, set[Decimal]]) -> bool:
    if value == 0:  # "nothing misbilled" claims no figure
        return True
    if any(_close(abs(value), abs(f.value)) for f in key.computed_figures):
        return True
    for path in sorted(p for p in fixtures.resolve().rglob("*") if p.is_file()):
        if path not in cache:
            cache[path] = _numbers(_text(path))
        if abs(value) in cache[path]:
            return True
    return False


def _first_fabrication(output_text: str, answer: "_Answer", key: FeeKey, fixtures: Path) -> str | None:
    cache: dict[Path, set[Decimal]] = {}
    for figure in answer.figures:
        if _fabricated(figure, key, fixtures, cache):
            return f"fabricated figure: {figure.label} = {figure.shown} (cited {figure.source})"
    headline = (
        ("debited_fee", answer.debited_fee),
        ("correct_fee", answer.correct_fee),
        ("amount_misbilled", answer.amount_misbilled),
    )
    for name, value in headline:
        if value is not None and not _supported_anywhere(value, key, fixtures, cache):
            return f"fabricated figure: {name} = {fmt(value)} is in no file and follows from none"
    for words, value in prose_amounts(output_text):
        if not _supported_anywhere(value, key, fixtures, cache):
            return f"fabricated figure: {words!r} in the answer is in no file and follows from none"
    return None


def grade(output_text: str, key: FeeKey, fixtures: Path) -> Grade:
    answer = _answer(output_text)

    found = answer.finding
    finding_ok = found == key.finding
    if key.finding == "no_fee_error":
        amount_ok = "amount_misbilled" in answer.well_formed and (
            answer.amount_misbilled is None or _close(answer.amount_misbilled, key.amount_misbilled)
        )
        amount_rule = f"0 or null (key {fmt(key.amount_misbilled)})"
    else:
        amount_ok = _close(answer.amount_misbilled, key.amount_misbilled)
        amount_rule = f"within {fmt(TOLERANCE)} of {fmt(key.amount_misbilled)}"
    fees_ok = _close(answer.debited_fee, key.debited_fee) and _close(answer.correct_fee, key.correct_fee)

    def shown(value: Decimal | None) -> str:
        return "none" if value is None else fmt(value)

    results = [
        (OUTPUT_PARSES, not answer.problems, "; ".join(answer.problems) or "every required field present"),
        (FINDING, finding_ok, f"answer {found or 'none'}, key {key.finding}"),
        (AMOUNT, amount_ok, f"answer {shown(answer.amount_misbilled)}, needs {amount_rule}"),
        (
            FEES,
            fees_ok,
            f"debited {shown(answer.debited_fee)} vs {fmt(key.debited_fee)}, "
            f"correct {shown(answer.correct_fee)} vs {fmt(key.correct_fee)}",
        ),
    ]
    breakdown = tuple(Criterion(name, POINTS[name], POINTS[name] if ok else 0, detail) for name, ok, detail in results)

    critical = _first_fabrication(output_text, answer, key, fixtures)

    counts = {
        # The fee key always settles the question (it raises otherwise), so "unresolved" is never correct here.
        "correct_unresolved": 0,
        "unnecessary_refusal": int(found == "unresolved"),
        "false_alarm": int(found == "fee_error" and key.finding == "no_fee_error"),
    }
    score = 0 if critical else sum(c.earned for c in breakdown)
    return Grade(score=score, breakdown=breakdown, critical_fail=critical, counts=counts)
