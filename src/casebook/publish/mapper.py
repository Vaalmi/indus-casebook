"""Map a run's real tickers and security names back to aliases before anything is published."""

import json
import re
from collections.abc import Callable
from importlib.resources import files
from typing import Any

from casebook.published_text import decoded_blob
from casebook.securities.master import load_master
from casebook.securities.scan import default_scan


class MappingError(RuntimeError):
    """A real ticker or security name survived mapping, so the record cannot be published."""


def _flexible(phrase: str) -> str:
    return r"\s+".join(map(re.escape, phrase.split()))


def alias_mapper() -> Callable[[str], str]:
    master = load_master()
    raw = json.loads((files("casebook.securities") / "real_names.json").read_text(encoding="utf-8"))
    by_ticker = {s.real_ticker: s.alias for s in master}
    names = sorted(
        ((name, by_ticker[ticker]) for ticker, ns in raw["names"].items() for name in ns),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
    named = [(re.compile(rf"(?<![A-Za-z0-9]){_flexible(n)}(?![A-Za-z0-9])", re.IGNORECASE), a) for n, a in names]
    issuers = [
        (re.compile(rf"(?<![A-Za-z0-9]){_flexible(n)}(?![A-Za-z0-9])", re.IGNORECASE), a)
        for n, a in raw["issuers"].items()
    ]
    tickers = re.compile(
        r"(?<![A-Za-z0-9])(" + "|".join(map(re.escape, sorted(by_ticker, key=len, reverse=True))) + r")(?![A-Za-z0-9])"
    )

    def map_text(text: str) -> str:
        for pattern, alias in named + issuers:
            text = pattern.sub(alias, text)
        return tickers.sub(lambda m: by_ticker[m.group(1)], text)

    return map_text


OMITTED = "<attachment omitted from the published record: the published book holds this file under aliases>"


def _walk(value: Any, map_text: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        # A file the run read, carried as base64 (a statement PDF, say), cannot be mapped in place.
        return OMITTED if decoded_blob(value) is not None else map_text(value)
    if isinstance(value, dict):
        return {map_text(str(k)): _walk(v, map_text) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v, map_text) for v in value]
    return value


def map_to_aliases(value: Any) -> Any:
    """Every string in a record or transcript, mapped; refused if a real identifier remains."""
    mapped = _walk(value, alias_mapper())
    leaks = default_scan().find(json.dumps(mapped, ensure_ascii=False))
    if leaks:
        raise MappingError(f"real identifiers remain after mapping: {sorted({h.identifier for h in leaks})}")
    return mapped
