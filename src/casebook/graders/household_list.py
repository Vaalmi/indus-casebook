"""The grader for a book-level task answered as a list of households: scores the households an answer names
against the key's set.

Any key that exposes the households it checked, the ones it finds (each with the identifiers an answer's entry
for it must name), the ones it leaves unresolved, and the figures it computes can be graded here; T-REC-05 and
T-REC-06 use it, and the book-level tax-lot sweeps can.

Each household gets one status from the key (found, unresolved, or cleared: checked and neither) and one from
the answer (named in "households", named in "unresolved", or neither). The set is the answer, so both set
criteria are essential and a pass needs it exact:

- none missed (35): every household the key finds is named in "households", and every household it leaves
  unresolved is named in one of the two lists;
- none wrongly named (35): no household is named in "households" that the key does not find, and none in
  "unresolved" that the key settles;
- evidence (20): each household the key finds is named with every identifier the key lists for it (the
  agreement and billing groups, or the accounts), anywhere in its entry;
- output parses (10).

The three counts are per household, since each named household is its own claim: naming a cleared (or
unknown) household is a false alarm; naming a household unresolved is a correct "unresolved" where the key
leaves it so, and an unnecessary refusal where the key settles it. A blanket refusal (finding "unresolved" with
no household named) counts once, as a correct "unresolved" where the key settles no household and leaves some
unresolved, and as an unnecessary refusal otherwise. It never passes: it names no household, so it earns no
evidence, and it meets neither set criterion unless the key settles no household, when it is still wrong not to
name the ones left open. An answer with no readable finding and "households" list names no set, so it earns
only what output parses gives it, which is nothing.
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from casebook.graders.common import (
    CORRECT_UNRESOLVED,
    FALSE_ALARM,
    OUTPUT_PARSES,
    UNNECESSARY_REFUSAL,
    UNRESOLVED,
    Figure,
    Grade,
    NotMoney,
    Support,
    figures,
    file_figures,
    grade_from,
    json_block,
    money,
)

FOUND, NONE_FOUND = "found", "none_found"
FINDINGS = (FOUND, NONE_FOUND, UNRESOLVED)
HOUSEHOLDS = "households"
REQUIRED_FIELDS = ("finding", HOUSEHOLDS, UNRESOLVED, "figures", "explanation")

NONE_MISSED = "none_missed"
NONE_WRONG = "none_wrongly_named"
EVIDENCE = "evidence"
POINTS = {OUTPUT_PARSES: 10, NONE_MISSED: 35, NONE_WRONG: 35, EVIDENCE: 20}
# Stands for every household in the "wrongly named" detail of a blanket refusal or an unreadable answer.
WHOLE_BOOK = "the whole book"


class KeyValue(Protocol):
    @property
    def value(self) -> Decimal: ...


class HouseholdListKey(Protocol):
    """What this grader needs of a book-level key."""

    @property
    def checked(self) -> tuple[str, ...]:
        """Every household the key examined."""
        ...

    @property
    def found(self) -> Mapping[str, tuple[str, ...]]:
        """The expected set: each household the key finds, with the identifiers an answer must name for it."""
        ...

    @property
    def unresolved(self) -> tuple[str, ...]:
        """The households the files leave unresolved."""
        ...

    @property
    def computed_figures(self) -> Sequence[KeyValue]: ...


def key_finding(key: HouseholdListKey) -> str:
    """The key's answer to the whole question."""
    if key.found:
        return FOUND
    return UNRESOLVED if key.unresolved else NONE_FOUND


@dataclass(frozen=True)
class _Answer:
    finding: str | None
    named: Mapping[str, str]  # each household in "households", with its entry as text
    unresolved: frozenset[str]
    figures: tuple[Figure, ...]
    problems: tuple[str, ...]
    # A finding and a "households" list could be read: without them the answer names no set to score.
    readable: bool
    # Every amount an entry states (a shortfall, a disallowed loss), judged by the fabricated-figure rule.
    amounts: tuple[tuple[str, Decimal], ...] = ()

    @property
    def blanket_refusal(self) -> bool:
        return self.finding == UNRESOLVED and not self.named and not self.unresolved


def _household_id(item: object) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, dict) and isinstance(item.get("household_id"), str):
        return str(item["household_id"])
    return None


# An entry's fields that hold identifiers or words, never an amount.
NOT_AMOUNTS = frozenset({"household_id", "explanation"})
_MONEY_TEXT = re.compile(r"\(?-?\$?\s?\d[\d,]*(?:\.\d+)?\)?")


def _amounts(where: str, value: object, found: list[tuple[str, Decimal]]) -> None:
    """Every number in an entry's value, and every string written as money, with where it sits; identifiers
    (SYN-..., T-..., dates) are not money and are left alone."""
    if isinstance(value, bool):
        return
    if isinstance(value, int | Decimal):
        found.append((where, abs(Decimal(value))))
    elif isinstance(value, str) and _MONEY_TEXT.fullmatch(value.strip()):
        try:
            amount = money(value.strip().strip("()"))
        except NotMoney:
            return
        if amount is not None:
            found.append((where, abs(amount)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _amounts(f"{where}[{index}]", item, found)
    elif isinstance(value, dict):
        for field, item in value.items():
            if field not in NOT_AMOUNTS:
                _amounts(f"{where}.{field}", item, found)


def _entries(
    data: dict[str, Any], name: str, problems: list[str], amounts: list[tuple[str, Decimal]] | None = None
) -> dict[str, str]:
    raw = data.get(name, [])
    if not isinstance(raw, list):
        problems.append(f"{name} is not a list")
        return {}
    entries: dict[str, str] = {}
    for index, item in enumerate(raw):
        household = _household_id(item)
        if household is None:
            problems.append(f"{name}[{index}] names no household_id")
            continue
        entries[household] = json.dumps(item, default=str)
        if amounts is not None:
            _amounts(f"{name}[{household}]", item, amounts)
    return entries


def _answer(output_text: str) -> _Answer:
    data = json_block(output_text)
    if isinstance(data, str):
        return _Answer(None, {}, frozenset(), (), (data,), readable=False)
    problems = [f"lacks {name}" for name in REQUIRED_FIELDS if name not in data]
    finding = data.get("finding")
    if "finding" in data and finding not in FINDINGS:
        problems.append(f"finding {finding!r} is not one of {', '.join(FINDINGS)}")
        finding = None
    amounts: list[tuple[str, Decimal]] = []
    named = _entries(data, HOUSEHOLDS, problems, amounts)
    unresolved = _entries(data, UNRESOLVED, problems, amounts)
    both = sorted(set(named) & set(unresolved))
    if both:
        problems.append(f"{', '.join(both)} named both found and unresolved; read as found")
    consistent = {
        FOUND: bool(named),
        NONE_FOUND: not named and not unresolved,
        UNRESOLVED: not named,
    }
    if finding in consistent and not consistent[str(finding)]:
        problems.append(f"finding {finding!r} does not match the households listed")
    if "explanation" in data and not isinstance(data["explanation"], str):
        problems.append("explanation is not text")
    cited = figures(data["figures"], problems) if "figures" in data else ()
    return _Answer(
        finding=str(finding) if finding is not None else None,
        named=named,
        unresolved=frozenset(unresolved) - set(named),
        figures=cited,
        problems=tuple(problems),
        readable=finding is not None and isinstance(data.get(HOUSEHOLDS), list),
        amounts=tuple(amounts),
    )


def _listed(households: Iterable[str]) -> str:
    return ", ".join(sorted(households)) or "none"


def grade(output_text: str, key: HouseholdListKey, fixtures: Path) -> Grade:
    answer = _answer(output_text)
    found, unresolved = set(key.found), set(key.unresolved)
    named = set(answer.named)
    expected = key_finding(key)

    names_a_set = answer.readable and not answer.blanket_refusal
    if not answer.readable:
        missed, wrong = {WHOLE_BOOK}, {WHOLE_BOOK}
        counts: dict[str, int] = dict.fromkeys((CORRECT_UNRESOLVED, UNNECESSARY_REFUSAL, FALSE_ALARM), 0)
    elif answer.blanket_refusal:
        # Right only that the files settle nothing, and even then it names none of the households they leave open.
        missed, wrong = (unresolved, set[str]()) if expected == UNRESOLVED else ({WHOLE_BOOK}, {WHOLE_BOOK})
        counts = {
            CORRECT_UNRESOLVED: int(expected == UNRESOLVED),
            UNNECESSARY_REFUSAL: int(expected != UNRESOLVED),
            FALSE_ALARM: 0,
        }
    else:
        missed = (found - named) | (unresolved - named - answer.unresolved)
        wrong = (named - found) | (answer.unresolved - unresolved)
        counts = {
            CORRECT_UNRESOLVED: len(answer.unresolved & unresolved),
            UNNECESSARY_REFUSAL: len(answer.unresolved - unresolved),
            # A household the key clears, or one the book does not hold.
            FALSE_ALARM: len(named - found - unresolved),
        }

    lacking = {
        household: [i for i in identifiers if i not in answer.named.get(household, "")]
        for household, identifiers in key.found.items()
    }
    lacking = {h: ids for h, ids in lacking.items() if h not in named or ids}
    results = [
        (
            OUTPUT_PARSES,
            POINTS[OUTPUT_PARSES],
            not answer.problems,
            "; ".join(answer.problems) or "every required field present",
        ),
        (
            NONE_MISSED,
            POINTS[NONE_MISSED],
            not missed,
            f"missed {_listed(missed)} (key finds {_listed(found)}, leaves unresolved {_listed(unresolved)})",
        ),
        (
            NONE_WRONG,
            POINTS[NONE_WRONG],
            not wrong,
            f"wrongly named {_listed(wrong)} (answer names {_listed(named)}, unresolved {_listed(answer.unresolved)})",
        ),
        (
            EVIDENCE,
            POINTS[EVIDENCE],
            names_a_set and not lacking,
            "; ".join(
                f"{h}: not named" if h not in named else f"{h}: lacks {', '.join(ids)}"
                for h, ids in sorted(lacking.items())
            )
            or ("every household the key finds is named with its evidence" if names_a_set else "no household named"),
        ),
    ]
    # A sweep over RMDs carries the IRS table figures it uses; one cited from the tables is judged as in rmd_review.
    table: Sequence[Decimal] = getattr(key, "table_figures", ())
    support = Support(fixtures, [f.value for f in key.computed_figures], table)
    critical = support.first_fabrication(output_text, file_figures(answer.figures, table), answer.amounts)
    return grade_from(results, critical, counts, essential=(NONE_MISSED, NONE_WRONG))
