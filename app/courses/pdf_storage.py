"""PDF reading and storage on the server volume (``{root}/{course_id}/v{n}.pdf``)."""

import hashlib
import os
from contextlib import suppress
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PyPdfError

from app.exceptions import PageNotFoundError, PdfUnavailableError

PDF_SIGNATURE = b"%PDF-"


@dataclass(frozen=True)
class PdfInfo:
    """Facts extracted from a validated PDF."""

    page_count: int
    fingerprints: tuple[str, ...]


def _fingerprint(page) -> str:  # type: ignore[no-untyped-def]
    contents = page.get_contents()
    raw = contents.get_data() if contents is not None else b""
    size = f"{page.mediabox.width}x{page.mediabox.height}".encode()
    return hashlib.sha256(size + b"|" + raw).hexdigest()


def _open(data: bytes) -> PdfReader:
    try:
        return PdfReader(BytesIO(data))
    except (PyPdfError, ValueError, OSError) as exc:
        raise ValueError("Le fichier n'est pas un PDF valide") from exc


class PdfStorage:
    """Validate, store and extract pages from versioned course PDFs."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def inspect(self, data: bytes) -> PdfInfo:
        """Return page count and deterministic SHA-256 page fingerprints."""
        if not data.startswith(PDF_SIGNATURE):
            raise ValueError("Le fichier n'est pas un PDF valide")
        reader = _open(data)
        if reader.is_encrypted:
            raise ValueError("Le PDF est chiffré")
        try:
            pages = list(reader.pages)
            fingerprints = tuple(_fingerprint(page) for page in pages)
        except (PyPdfError, ValueError, OSError, KeyError) as exc:
            raise ValueError("Le fichier n'est pas un PDF valide") from exc
        if not pages:
            raise ValueError("Le PDF ne contient aucune page")
        return PdfInfo(page_count=len(pages), fingerprints=fingerprints)

    def path_for(self, course_id: int, version_number: int) -> Path:
        """Location of one version file."""
        return self._root / str(course_id) / f"v{version_number}.pdf"

    def exists(self, course_id: int, version_number: int) -> bool:
        """Whether the version file is present on the volume."""
        return self.path_for(course_id, version_number).is_file()

    def save(self, course_id: int, version_number: int, data: bytes) -> Path:
        """Write a version file atomically."""
        path = self.path_for(course_id, version_number)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)
        return path

    def delete(self, course_id: int, version_number: int) -> None:
        """Remove a version file (and a leftover temporary file), then the folder if empty."""
        path = self.path_for(course_id, version_number)
        with suppress(OSError):
            path.unlink(missing_ok=True)
            path.with_suffix(".tmp").unlink(missing_ok=True)
            path.parent.rmdir()

    def read_page(self, course_id: int, version_number: int, page_number: int) -> bytes:
        """Return one page as a standalone single-page PDF."""
        path = self.path_for(course_id, version_number)
        if not path.is_file():
            raise PdfUnavailableError()
        reader = _open(path.read_bytes())
        if not 1 <= page_number <= len(reader.pages):
            raise PageNotFoundError()
        writer = PdfWriter()
        writer.add_page(reader.pages[page_number - 1])
        buffer = BytesIO()
        writer.write(buffer)
        return buffer.getvalue()
