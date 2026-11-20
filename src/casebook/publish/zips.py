"""Zips the release ships (case packets, the review packet), written the same way on every machine: names sorted, one
fixed date and permission, no compression (zlib's output differs between builds of it). docs/PLAN.md, Determinism:
"PDFs and zips are written with fixed dates and IDs"."""

import io
import zipfile
from pathlib import PurePosixPath

FIXED_DATE = (1980, 1, 1, 0, 0, 0)
FILE_MODE = 0o100644 << 16


class ZipError(ValueError):
    pass


def _checked(name: str) -> str:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "\\" in name or name.endswith("/"):
        raise ZipError(f"{name!r} is not a plain relative file name")
    return name


def write_zip(files: dict[str, bytes]) -> bytes:
    """The zip of `files` (name to bytes); the same input gives the same bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(_checked(name), date_time=FIXED_DATE)
            info.external_attr = FILE_MODE
            info.create_system = 3
            archive.writestr(info, files[name])
    return buffer.getvalue()


def read_zip(data: bytes) -> dict[str, bytes]:
    """Every file in a zip, by name. A zip that is not one, holds a folder entry, an unsafe or repeated name, is
    refused: a gate reads every member, and nothing a gate cannot name may hide in one."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            if len(set(names)) != len(names):
                raise ZipError("a name appears twice")
            return {_checked(i.filename): archive.read(i) for i in infos}
    except zipfile.BadZipFile as error:
        raise ZipError(f"not a zip ({error})") from error
