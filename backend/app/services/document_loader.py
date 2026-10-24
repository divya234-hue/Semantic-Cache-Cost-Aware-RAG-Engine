import hashlib
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from backend.app.models.domain import LoadedDocument


class DocumentLoadError(Exception):
    """Raised when a supported corpus document cannot be read safely."""


class NoDocumentsFoundError(Exception):
    """Raised when the configured corpus contains no supported documents."""


class DocumentLoader:
    supported_suffixes = {".txt", ".pdf"}

    def __init__(self, documents_dir: Path, max_document_bytes: int) -> None:
        self.documents_dir = documents_dir
        self.max_document_bytes = max_document_bytes

    def load_all(self) -> list[LoadedDocument]:
        if not self.documents_dir.exists() or not self.documents_dir.is_dir():
            raise DocumentLoadError("The configured documents directory is unavailable.")

        documents: list[LoadedDocument] = []
        paths = sorted(
            path
            for path in self.documents_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in self.supported_suffixes
        )
        for path in paths:
            relative_path = path.relative_to(self.documents_dir).as_posix()
            try:
                if path.stat().st_size > self.max_document_bytes:
                    raise DocumentLoadError(
                        f"Document exceeds the configured size limit: {relative_path}"
                    )
                text = self._read_text(path)
            except (OSError, UnicodeDecodeError, PdfReadError) as exc:
                raise DocumentLoadError(
                    f"Unable to read corpus document: {relative_path}"
                ) from exc

            if not text.strip():
                continue
            document_id = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]
            documents.append(
                LoadedDocument(
                    document_id=document_id,
                    source_path=relative_path,
                    text=text,
                )
            )
        return documents

    @staticmethod
    def _read_text(path: Path) -> str:
        if path.suffix.lower() == ".txt":
            return path.read_text(encoding="utf-8")
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
