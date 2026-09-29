import io
import zipfile

import pytest

from app.core.exceptions import ValidationError
from app.domains.documents.upload_safety import (
    MAX_NAME_LENGTH,
    read_limited,
    sanitize_filename,
    sniff_content,
)
from app.models.document import FileType


class FakeUpload:
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)
        self.bytes_read = 0

    async def read(self, n: int = -1) -> bytes:
        chunk = self._buf.read(n)
        self.bytes_read += len(chunk)
        return chunk


# --- sanitize_filename -----------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("report.pdf", "report.pdf"),
        ("../../etc/passwd", "passwd"),
        ("..\\..\\windows\\system32\\evil.docx", "evil.docx"),
        ("/abs/path/notes.md", "notes.md"),
        ("a/b/../c.txt", "c.txt"),
        ("we<i>rd|na:me?.pdf", "we_i_rd_na_me_.pdf"),
        ("bad\x00name\n.txt", "badname.txt"),
        ("...hidden.pdf", "hidden.pdf"),
        ("   ", "file"),
        (None, "file"),
        ("..", "file"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_never_contains_path_separators_or_traversal():
    for raw in ["../x.pdf", "..%2f..%2fx.pdf", "a\\..\\b.pdf", "x/../../y.pdf"]:
        out = sanitize_filename(raw)
        assert "/" not in out and "\\" not in out and not out.startswith(".")


def test_sanitize_filename_bounds_length_and_keeps_extension():
    out = sanitize_filename("a" * 500 + ".pdf")
    assert len(out) <= MAX_NAME_LENGTH and out.endswith(".pdf")


def test_sanitize_filename_keeps_unicode_letters():
    assert sanitize_filename("règlement_2024.pdf") == "règlement_2024.pdf"


# --- read_limited ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_limited_returns_content_within_limit():
    assert await read_limited(FakeUpload(b"x" * 100), 1000) == b"x" * 100


@pytest.mark.asyncio
async def test_read_limited_stops_early_when_over_limit():
    upload = FakeUpload(b"x" * (5 * 1024 * 1024))
    with pytest.raises(ValidationError, match="maximum size"):
        await read_limited(upload, 1024 * 1024, 1)
    # Must not have buffered the whole 5MB body.
    assert upload.bytes_read < 5 * 1024 * 1024


# --- sniff_content ---------------------------------------------------------------


def make_zip(names: list[str], payload: bytes = b"x") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n in names:
            zf.writestr(n, payload)
    return buf.getvalue()


def test_sniff_accepts_real_types():
    sniff_content(b"%PDF-1.7\n...", FileType.pdf)
    sniff_content(make_zip(["word/document.xml"]), FileType.docx)
    sniff_content(b"# heading\ntext", FileType.md)
    sniff_content(b"a,b\n1,2", FileType.csv)


def test_sniff_rejects_mismatched_content():
    with pytest.raises(ValidationError):
        sniff_content(b"MZ\x90\x00 executable", FileType.pdf)
    with pytest.raises(ValidationError):
        sniff_content(b"plain text", FileType.docx)
    with pytest.raises(ValidationError):
        sniff_content(make_zip(["other.xml"]), FileType.docx)  # zip, but not a docx
    with pytest.raises(ValidationError):
        sniff_content(b"text\x00\x01binary", FileType.txt)


def test_sniff_rejects_docx_zip_bomb(monkeypatch):
    monkeypatch.setattr("app.domains.documents.upload_safety.MAX_DOCX_UNCOMPRESSED_BYTES", 1000)
    bomb = make_zip(["word/document.xml"], payload=b"0" * 10_000)
    with pytest.raises(ValidationError, match="expands"):
        sniff_content(bomb, FileType.docx)
