"""Fail on any float in the packages that handle money: literals, calls and annotations.

`--except FILE` leaves out one file that must exist: the boundary with an outside program that computes in
float (Tax-Calculator, through `tax/crosscheck.py`), which converts every figure to Decimal as it leaves.
"""

import argparse
import ast
import sys
from pathlib import Path


def float_uses(source: str, filename: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            found.append(f"{filename}:{node.lineno}: float literal {node.value!r}; use Decimal")
        elif isinstance(node, ast.Name) and node.id == "float":
            found.append(f"{filename}:{node.lineno}: float; use Decimal")
    return found


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folders", nargs="+", type=Path)
    parser.add_argument("--except", dest="excepted", action="append", type=Path, default=[])
    args = parser.parse_args(argv)
    missing = [path for path in args.excepted if not path.is_file()]
    for path in missing:
        print(f"{path}: excepted from the float check but not a file", file=sys.stderr)
    excepted = {path.resolve() for path in args.excepted}
    found: list[str] = []
    for folder in args.folders:
        for path in sorted(folder.rglob("*.py")):
            if path.resolve() not in excepted:
                found += float_uses(path.read_text(encoding="utf-8"), path.as_posix())
    for line in found:
        print(line, file=sys.stderr)
    return 1 if found or missing else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
