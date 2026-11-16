"""The security master: internal ID, alias and real ticker, and no other field."""

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

MASTER_FIELDS = ("internal_id", "alias", "real_ticker")


class MasterFormatError(ValueError):
    pass


@dataclass(frozen=True)
class Security:
    internal_id: str
    alias: str
    real_ticker: str


def parse_master(raw: Any) -> tuple[Security, ...]:
    if not isinstance(raw, list):
        raise MasterFormatError("the security master is a list of securities")
    securities: list[Security] = []
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) != set(MASTER_FIELDS):
            keys = sorted(entry) if isinstance(entry, dict) else entry
            raise MasterFormatError(f"a security has exactly the fields {MASTER_FIELDS}, not {keys}")
        securities.append(Security(**{k: str(entry[k]) for k in MASTER_FIELDS}))
    for field in MASTER_FIELDS:
        values = [getattr(s, field) for s in securities]
        if len(set(values)) != len(values):
            raise MasterFormatError(f"{field} values repeat in the security master")
    return tuple(securities)


def load_master() -> tuple[Security, ...]:
    text = (files("casebook.securities") / "master.json").read_text(encoding="utf-8")
    return parse_master(json.loads(text))


def by_id(master: tuple[Security, ...]) -> dict[str, Security]:
    return {s.internal_id: s for s in master}
