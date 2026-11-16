"""The dates every household shares (docs/SPEC.md, The book)."""

from datetime import date, timedelta

PRIOR_YEAR_END = date(2024, 12, 31)
OPENING_DATE = date(2025, 1, 1)
SCENARIO_DATE = date(2026, 4, 15)

QUARTER_ENDS = (
    date(2025, 3, 31),
    date(2025, 6, 30),
    date(2025, 9, 30),
    date(2025, 12, 31),
    date(2026, 3, 31),
)


def is_weekday(day: date) -> bool:
    return day.weekday() < 5


def add_weekdays(day: date, count: int) -> date:
    current = day
    while count > 0:
        current += timedelta(days=1)
        if is_weekday(current):
            count -= 1
    return current


def weekdays(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        if is_weekday(current):
            days.append(current)
        current += timedelta(days=1)
    return days


def parse_date(text: str) -> date:
    return date.fromisoformat(text)
