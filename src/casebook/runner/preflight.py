"""What must hold before a run starts. Each refusal is a named error."""

import csv
import hashlib
import io
import json
from datetime import date
from pathlib import Path
from typing import Any

from casebook.model.files import METADATA, REAL_TICKERS, household_dir, read_json, read_manifest
from casebook.tasks.task import BOOK


class RunRefusedError(RuntimeError):
    pass


class UnknownHouseholdError(RunRefusedError):
    pass


class SealedFileReachableError(RunRefusedError):
    pass


class FutureEvidenceError(RunRefusedError):
    pass


class NotRealTickersError(RunRefusedError):
    pass


def require_real_tickers(book: Path) -> None:
    """Every run reads the real-ticker build (docs/SPEC.md, Aliases)."""
    if read_json(book, METADATA).get("securities") != REAL_TICKERS:
        raise NotRealTickersError(
            f"{book} is not a real-ticker build; runs read `casebook build --real-tickers` output"
        )


class OutsideBookError(RunRefusedError):
    pass


def require_book_files(book: Path, household_id: str) -> None:
    """Nothing is read from outside the book: no link on the way to the household's folder or inside it;
    for a book-level task, every household's."""
    if household_id == BOOK:
        for household in read_manifest(book).households:
            require_book_files(book, household.household_id)
        return
    folder = book / household_dir(household_id)
    for step in (folder.parent, folder):
        if step.is_symlink():
            raise OutsideBookError(f"{step.relative_to(book).as_posix()} is a link out of the book")
    root = folder.resolve()
    if not root.is_relative_to(book.resolve()):
        raise OutsideBookError(f"{household_id}'s folder is outside the book")
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise OutsideBookError(f"{path.relative_to(root).as_posix()} in {household_id} is a link out of the book")


def require_household(book: Path, household_id: str) -> None:
    households = {h.household_id for h in read_manifest(book).households}
    if household_id == BOOK and households:
        return
    if household_id not in households:
        raise UnknownHouseholdError(
            f"household {household_id} is not in the book manifest; runs use book households only"
        )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_sealed(workspace: Path, sealed: list[Path]) -> None:
    """No sealed file, nor a link to anything, may be inside the workspace."""
    sealed_hashes = {_sha(p): p for p in sealed}
    for path in sorted(workspace.rglob("*")):
        relative = path.relative_to(workspace).as_posix()
        if path.is_symlink():
            raise SealedFileReachableError(f"{relative} is a link; a workspace holds plain copies only")
        if path.is_file() and _sha(path) in sealed_hashes:
            raise SealedFileReachableError(f"{relative} is a copy of sealed file {sealed_hashes[_sha(path)].name}")


def _late(item: dict[str, Any], cutoff: date) -> bool:
    known = item.get("known_as_of")
    return known is not None and date.fromisoformat(str(known)) > cutoff


def _walk(value: Any, cutoff: date, where: str) -> str | None:
    if isinstance(value, dict):
        if _late(value, cutoff):
            return where
        for key, child in value.items():
            found = _walk(child, cutoff, f"{where}.{key}")
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _walk(child, cutoff, f"{where}[{index}]")
            if found:
                return found
    return None


def require_cutoff(workspace: Path, cutoff: date) -> None:
    """Scan the workspace itself, after loading, for any row or document known after the cutoff."""
    for path in sorted(workspace.rglob("*")):
        relative = path.relative_to(workspace).as_posix()
        if path.suffix == ".csv":
            for line, row in enumerate(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))), start=2):
                if _late(row, cutoff):
                    raise FutureEvidenceError(f"{relative} line {line} is known after the cutoff {cutoff}")
        elif path.suffix == ".json":
            found = _walk(json.loads(path.read_text(encoding="utf-8")), cutoff, relative)
            if found:
                raise FutureEvidenceError(f"{found} is known after the cutoff {cutoff}")
        elif path.suffix == ".pdf":
            index = workspace / "documents" / "index.json"
            listed = json.loads(index.read_text(encoding="utf-8"))["documents"] if index.is_file() else []
            if path.name not in {d["file"] for d in listed}:
                raise FutureEvidenceError(f"{relative} is not in the document index, so its date is unknown")
