"""Upload hardening: filename sanitizing, bounded reads and content sniffing.

Client-supplied filenames and content types are untrusted. The stored path is built
from a sanitized name, the size limit is enforced while reading (not after loading the
whole body), and the bytes must actually look like the type the extension claims.
"""

import io
import re
import unicodedata
import zipfile

from fastapi import UploadFile

from app.core.exceptions import ValidationError
from app.models.document import FileType

READ_CHUNK = 1024 * 1024
MAX_NAME_LENGTH = 150
# A docx is a zip; refuse archives that expand far beyond the upload limit.
MAX_DOCX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_DOCX_ENTRIES = 5000

TEXT_TYPES = {FileType.md, FileType.txt, FileType.html, FileType.csv, FileType.json}


def sanitize_filename(name: str | None) -> str:
    """Return a safe basename: no path components, no control characters, restricted
    charset, bounded length, extension preserved. Never empty."""
    name = unicodedata.normalize("NFKC", name or "")
    name = name.replace("\\", "/").rsplit("/", 1)[-1]  # drop any directory part
    name = "".join(ch for ch in name if ch.isprintable())
    name = re.sub(r"[^\w.\- ()]", "_", name, flags=re.UNICODE)
    name = re.sub(r"\s+", " ", name).strip(" .")  # no leading/trailing dots or spaces
    if not name:
        return "file"
    if len(name) > MAX_NAME_LENGTH:
        stem, dot, ext = name.rpartition(".")
        if dot and len(ext) <= 10:
            name = stem[: MAX_NAME_LENGTH - len(ext) - 1] + "." + ext
        else:
            name = name[:MAX_NAME_LENGTH]
    return name


async def read_limited(file: UploadFile, max_bytes: int, max_mb: int | None = None) -> bytes:
    """Read the upload in chunks and stop as soon as it exceeds the limit, so an
    oversized body is never fully buffered in memory."""
    parts: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            limit = f"{max_mb}MB" if max_mb is not None else f"{max_bytes} bytes"
            raise ValidationError(f"File exceeds maximum size of {limit}")
        parts.append(chunk)
    return b"".join(parts)


def sniff_content(content: bytes, file_type: FileType) -> None:
    """Raise ValidationError unless the bytes plausibly match the claimed type."""
    if file_type == FileType.pdf:
        if b"%PDF-" not in content[:1024]:
            raise ValidationError("File content is not a valid PDF")
    elif file_type == FileType.docx:
        _check_docx(content)
    elif file_type == FileType.image:
        _check_image(content)
    elif file_type in TEXT_TYPES:
        if b"\x00" in content[:8192]:
            raise ValidationError(f"File content is binary, not valid {file_type.value} text")


def _check_docx(content: bytes) -> None:
    if not content.startswith(b"PK\x03\x04"):
        raise ValidationError("File content is not a valid DOCX")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_DOCX_ENTRIES:
                raise ValidationError("DOCX contains too many entries")
            if sum(i.file_size for i in infos) > MAX_DOCX_UNCOMPRESSED_BYTES:
                raise ValidationError("DOCX expands beyond the allowed size")
            if "word/document.xml" not in zf.namelist():
                raise ValidationError("File content is not a valid DOCX")
    except zipfile.BadZipFile as e:
        raise ValidationError("File content is not a valid DOCX") from e


def _check_image(content: bytes) -> None:
    is_png = content.startswith(b"\x89PNG\r\n\x1a\n")
    is_jpeg = content.startswith(b"\xff\xd8\xff")
    is_webp = content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    if not (is_png or is_jpeg or is_webp):
        raise ValidationError("File content is not a valid PNG, JPEG or WebP image")
