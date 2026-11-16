"""Fail when an installed package is GPL or AGPL, declares no licence, or is on the deny-list.

Package metadata alone is not enough: tenforty declares MIT and bundles GPL code, so
known offenders are also refused by name (docs/PLAN.md, Choices and why).
"""

import argparse
import re
import sys
from collections.abc import Iterable
from importlib.metadata import Distribution, distributions
from pathlib import Path

DENIED = {
    "policyengine": "AGPL",
    "policyengine-core": "AGPL",
    "policyengine-us": "AGPL",
    "tenforty": "bundles GPL code (OpenTaxSolver) behind an MIT declaration",
    "ustaxes": "AGPL",
}
_GPL_ID = re.compile(r"(?<![A-Za-z])A?GPL(?:v\d+)?(?![A-Za-z])", re.IGNORECASE)
_GPL_WORDS = re.compile(r"GNU (Affero )?General Public License", re.IGNORECASE)
_LESSER = re.compile(r"Lesser|Library|LGPL", re.IGNORECASE)


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _gpl_text(text: str) -> bool:
    if _LESSER.search(text):
        return False
    return bool(_GPL_ID.search(text) or _GPL_WORDS.search(text))


class ExpressionError(ValueError):
    pass


def _gpl_expression(expression: str) -> bool:
    """Whether an SPDX expression requires GPL: every OR alternative does, or any AND part does.

    `X WITH exception` is judged by X. Grouping by parentheses is respected.
    """
    tokens = re.findall(r"\(|\)|[^\s()]+", expression)
    position = 0

    def peek() -> str | None:
        return tokens[position] if position < len(tokens) else None

    def take() -> str:
        nonlocal position
        if position >= len(tokens):
            raise ExpressionError(f"unfinished licence expression {expression!r}")
        position += 1
        return tokens[position - 1]

    def term() -> bool:
        token = take()
        if token == "(":
            value = either()
            if take() != ")":
                raise ExpressionError(f"unbalanced licence expression {expression!r}")
        else:
            value = _gpl_text(token)
        if peek() == "WITH":
            take()
            take()
        return value

    def both() -> bool:
        value = term()
        while peek() == "AND":
            take()
            value = term() or value
        return value

    def either() -> bool:
        value = both()
        while peek() == "OR":
            take()
            value = both() and value
        return value

    result = either()
    if peek() is not None:
        raise ExpressionError(f"unexpected {peek()!r} in licence expression {expression!r}")
    return result


def declared(dist: Distribution) -> tuple[str, list[str]]:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return "expression", [expression]
    classifiers = [c for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")]
    specific = [c for c in classifiers if c != "License :: OSI Approved"]
    if specific:
        return "classifier", specific
    text = (meta.get("License") or "").strip()
    return ("text", [text]) if text else ("none", [])


def problems(dists: Iterable[Distribution]) -> list[str]:
    found: list[str] = []
    for dist in dists:
        name = normalize(dist.metadata["Name"] or "unknown")
        if name in DENIED:
            found.append(f"{name}: refused by name ({DENIED[name]})")
            continue
        how, values = declared(dist)
        if how == "none":
            found.append(f"{name}: declares no licence; check it by hand before adding it")
        elif how == "expression":
            try:
                if _gpl_expression(values[0]):
                    found.append(f"{name}: {values[0]}")
            except ExpressionError as error:
                found.append(f"{name}: {error}; check it by hand")
        elif how != "expression" and any(_gpl_text(v) for v in values):
            found.append(f"{name}: {'; '.join(values)}")
    return sorted(set(found))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, action="append", help="scan these site-packages folders instead")
    args = parser.parse_args(argv)
    dists = distributions(path=[str(p) for p in args.path]) if args.path else distributions()
    found = problems(dists)
    for line in found:
        print(f"licence check: {line}", file=sys.stderr)
    if not found:
        print("licence check: no GPL or AGPL package installed")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
