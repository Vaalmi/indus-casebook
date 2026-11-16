"""Fail on any float in the packages that handle money: literals, calls and annotations."""

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
    found: list[str] = []
    for folder in argv:
        for path in sorted(Path(folder).rglob("*.py")):
            found += float_uses(path.read_text(encoding="utf-8"), path.as_posix())
    for line in found:
        print(line, file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
