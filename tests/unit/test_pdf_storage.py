"""Unit tests for the PDF validation and storage service."""

from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.courses.pdf_storage import PdfStorage
from app.exceptions import PageNotFoundError, PdfUnavailableError
from tests.helpers import make_pdf_bytes, read_single_page_width


@pytest.fixture
def storage(tmp_path: Path) -> PdfStorage:
    """Temporary PDF storage instance."""
    return PdfStorage(tmp_path / "storage")


def test_inspect_returns_page_count_and_one_fingerprint_per_page(storage: PdfStorage) -> None:
    info = storage.inspect(make_pdf_bytes(3))
    assert info.page_count == 3
    assert len(info.fingerprints) == 3
    assert len(set(info.fingerprints)) == 3
    assert all(len(fingerprint) == 64 for fingerprint in info.fingerprints)


def test_fingerprints_are_deterministic(storage: PdfStorage) -> None:
    pdf = make_pdf_bytes(2)
    assert storage.inspect(pdf).fingerprints == storage.inspect(pdf).fingerprints


@pytest.mark.parametrize(
    "data",
    [b"", b"PK\x03\x04 word document", b"%PDF", b"%PDF-1.4 garbage", b"%PDF-1.4\n" + b"\0" * 40],
    ids=["empty", "docx", "short-signature", "corrupt-text", "corrupt-binary"],
)
def test_invalid_pdf_is_rejected(storage: PdfStorage, data: bytes) -> None:
    with pytest.raises(ValueError):
        storage.inspect(data)


def test_encrypted_pdf_is_rejected(storage: PdfStorage) -> None:
    with pytest.raises(ValueError, match="chiffré"):
        storage.inspect(make_pdf_bytes(2, password="secret"))


def test_pdf_without_pages_is_rejected(storage: PdfStorage) -> None:
    buffer = BytesIO()
    PdfWriter().write(buffer)
    with pytest.raises(ValueError):
        storage.inspect(buffer.getvalue())


def test_save_writes_versioned_file(storage: PdfStorage) -> None:
    path = storage.save(7, 1, make_pdf_bytes(2))
    assert path == storage.path_for(7, 1)
    assert path.name == "v1.pdf"
    assert path.parent.name == "7"
    assert storage.exists(7, 1)
    assert not storage.exists(7, 2)


def test_read_page_returns_a_single_page_pdf(storage: PdfStorage) -> None:
    storage.save(7, 1, make_pdf_bytes(3))
    assert read_single_page_width(storage.read_page(7, 1, 2)) == 201.0


@pytest.mark.parametrize("page_number", [0, 4, -1])
def test_read_page_out_of_range(storage: PdfStorage, page_number: int) -> None:
    storage.save(7, 1, make_pdf_bytes(3))
    with pytest.raises(PageNotFoundError):
        storage.read_page(7, 1, page_number)


def test_read_page_of_missing_file(storage: PdfStorage) -> None:
    with pytest.raises(PdfUnavailableError):
        storage.read_page(7, 1, 1)
