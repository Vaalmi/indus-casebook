"""Which key and grader each task names, and the hash a run records for them."""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from casebook.graders import fee_reconciliation as fee_grader
from casebook.keys import fee_reconciliation as fee_keys
from casebook.model.dates import parse_date


class UnknownGraderError(KeyError):
    pass


@dataclass(frozen=True)
class GraderSpec:
    name: str
    key: Callable[[Path, dict[str, Any]], Any]
    grade: Callable[[str, Any, Path], Any]
    sources: tuple[Path, ...]

    def sha256(self) -> str:
        digest = hashlib.sha256()
        for path in self.sources:
            digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
        return digest.hexdigest()


def _quarter_end(params: dict[str, Any]) -> date:
    value = params["quarter_end"]
    return value if isinstance(value, date) else parse_date(str(value))


GRADERS = {
    "fee_reconciliation": GraderSpec(
        name="fee_reconciliation",
        key=lambda household, params: fee_keys.fee_key(household, _quarter_end(params)),
        grade=fee_grader.grade,
        sources=(Path(fee_keys.__file__), Path(fee_grader.__file__)),
    )
}


def grader(name: str) -> GraderSpec:
    if name not in GRADERS:
        raise UnknownGraderError(f"no grader named {name!r}")
    return GRADERS[name]
