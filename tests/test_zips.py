import io
import zipfile

import pytest

from casebook.publish.zips import ZipError, read_zip, write_zip


def test_a_zip_reads_back_what_was_written() -> None:
    files = {"b/c.csv": b"x,y\n", "NOTICE.txt": b"notice\n", "a.json": b"{}"}
    assert read_zip(write_zip(files)) == files


def test_the_same_files_give_the_same_bytes_whatever_their_order() -> None:
    first = write_zip({"a": b"1", "b": b"2"})
    assert first == write_zip({"b": b"2", "a": b"1"})
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert [i.filename for i in archive.infolist()] == ["a", "b"]
        assert {i.date_time for i in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}
        assert {i.compress_type for i in archive.infolist()} == {zipfile.ZIP_STORED}


@pytest.mark.parametrize("name", ["", "/etc/passwd", "../x", "a/../../x", "a\\b", "folder/"])
def test_an_unsafe_name_is_refused(name: str) -> None:
    with pytest.raises(ZipError):
        write_zip({name: b""})


def test_a_zip_the_gates_cannot_read_whole_is_refused() -> None:
    with pytest.raises(ZipError, match="not a zip"):
        read_zip(b"not a zip")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../outside.csv", b"x")
    with pytest.raises(ZipError, match="plain relative"):
        read_zip(buffer.getvalue())
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("folder/", b"")
    with pytest.raises(ZipError):
        read_zip(buffer.getvalue())
