import pytest

from app.core.exceptions import ValidationError
from app.domains.documents.service import DocumentService
from app.models.document import FileType


class FakeUploadFile:
    def __init__(self, filename: str | None):
        self.filename = filename


def test_validate_upload_accepts_known_extensions():
    service = DocumentService()
    assert service._validate_upload(FakeUploadFile("report.pdf")) == FileType.pdf
    assert service._validate_upload(FakeUploadFile("notes.md")) == FileType.md
    assert service._validate_upload(FakeUploadFile("data.docx")) == FileType.docx
    assert service._validate_upload(FakeUploadFile("plain.txt")) == FileType.txt


def test_validate_upload_rejects_unknown_extension():
    service = DocumentService()
    with pytest.raises(ValidationError):
        service._validate_upload(FakeUploadFile("malware.exe"))


def test_validate_upload_rejects_missing_filename():
    service = DocumentService()
    with pytest.raises(ValidationError):
        service._validate_upload(FakeUploadFile(None))


def test_validate_upload_rejects_no_extension():
    service = DocumentService()
    with pytest.raises(ValidationError):
        service._validate_upload(FakeUploadFile("noextension"))
