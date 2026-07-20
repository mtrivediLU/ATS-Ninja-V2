"""Safe, local-only resume document text extraction.

This module deliberately returns text rather than a parsed candidate profile.
It is an ingestion boundary: it validates untrusted bytes, performs only
mechanical cleanup, and never writes the upload to a durable location.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from charset_normalizer import from_bytes
from pypdf import PdfReader

MAX_DOCX_MEMBERS = 1_000
MAX_DOCX_UNCOMPRESSED_BYTES = 25 * 1024 * 1024
MAX_DOCX_MEMBER_BYTES = 10 * 1024 * 1024
MIN_MEANINGFUL_TEXT_LENGTH = 20

PDF_MIME_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream", ""}
DOCX_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",
    "",
}
TEXT_MIME_TYPES = {"text/plain", "application/octet-stream", ""}


class ResumeExtractionError(ValueError):
    """A stable, client-safe extraction failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ResumeExtraction:
    """Safe metadata and reviewed-text candidate returned to the API layer."""

    filename: str
    mime_type: str
    size_bytes: int
    extraction_method: str
    text: str
    character_count: int
    page_count: int | None
    warnings: tuple[str, ...] = ()
    truncated: bool = False


def extract_resume_document(
    *,
    filename: str | None,
    content_type: str | None,
    content: bytes,
    max_bytes: int,
    max_pdf_pages: int,
    max_text_characters: int,
) -> ResumeExtraction:
    """Validate and extract one in-memory PDF, DOCX, or TXT resume upload."""
    safe_filename = _validate_filename(filename)
    if not content:
        raise ResumeExtractionError("empty_file", "The uploaded file is empty.")
    if len(content) > max_bytes:
        raise ResumeExtractionError("file_too_large", "The uploaded file exceeds the 10 MB limit.")

    extension = safe_filename.rsplit(".", 1)[1].lower()
    mime_type = (content_type or "").lower().split(";", 1)[0].strip()
    if extension == "doc":
        raise ResumeExtractionError(
            "legacy_doc_unsupported",
            "Legacy .doc files are not supported yet. Save the document as .docx, PDF, or plain text and try again.",
        )
    if extension == "pdf":
        if mime_type not in PDF_MIME_TYPES:
            raise ResumeExtractionError("unsupported_file_type", "The file type does not match a PDF document.")
        text, page_count = _extract_pdf(content, max_pdf_pages)
        method = "pdf_text"
    elif extension == "docx":
        if mime_type not in DOCX_MIME_TYPES:
            raise ResumeExtractionError("unsupported_file_type", "The file type does not match a DOCX document.")
        text = _extract_docx(content)
        page_count = None
        method = "docx_text"
    elif extension == "txt":
        if mime_type not in TEXT_MIME_TYPES:
            raise ResumeExtractionError("unsupported_file_type", "The file type does not match a plain-text document.")
        text = _extract_text(content)
        page_count = None
        method = "plain_text"
    else:
        raise ResumeExtractionError("unsupported_file_type", "Upload a PDF, DOCX, or TXT resume file.")

    normalized = normalize_extracted_text(text)
    if len(normalized) < MIN_MEANINGFUL_TEXT_LENGTH:
        if extension == "pdf":
            raise ResumeExtractionError(
                "scanned_pdf",
                "No readable text was found. This PDF may be scanned or image-based. Upload a text-based PDF, DOCX, or TXT file.",
            )
        raise ResumeExtractionError(
            "extracted_text_too_short", "The document did not contain enough readable resume text."
        )
    if len(normalized) > max_text_characters:
        raise ResumeExtractionError(
            "extracted_text_too_long",
            "The extracted resume text is too long. Shorten the document before continuing.",
        )
    return ResumeExtraction(
        filename=safe_filename,
        mime_type=_safe_mime_type(extension),
        size_bytes=len(content),
        extraction_method=method,
        text=normalized,
        character_count=len(normalized),
        page_count=page_count,
    )


_BULLET_MARKER_NO_GAP = re.compile(r"^(\s*[\-*•])([A-Za-z])", flags=re.MULTILINE)


def normalize_extracted_text(text: str) -> str:
    """Perform bounded mechanical cleanup without changing candidate claims."""
    normalized = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\x00", "")
    normalized = "".join(
        character for character in normalized if character in "\n\t" or unicodedata.category(character)[0] != "C"
    )
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    # PDF text extraction commonly reconstructs a bullet glyph immediately
    # against its text ("•Managed cloud infrastructure") because the visual
    # gap is glyph positioning, not a literal space character. Restore the
    # gap so the reviewed text reads correctly and downstream bullet
    # detection sees a normal marker; letters only, so numeric leads like
    # "-5%" are left untouched.
    normalized = _BULLET_MARKER_NO_GAP.sub(r"\1 \2", normalized)
    return re.sub(r"\n{4,}", "\n\n\n", normalized).strip()


def _validate_filename(filename: str | None) -> str:
    if not filename or len(filename) > 255 or "\x00" in filename or "/" in filename or "\\" in filename:
        raise ResumeExtractionError("unsupported_file_type", "Upload a PDF, DOCX, or TXT resume file.")
    if filename.startswith(".") or filename.count(".") != 1:
        raise ResumeExtractionError("unsupported_file_type", "Upload a PDF, DOCX, or TXT resume file.")
    base, extension = filename.rsplit(".", 1)
    if not base or extension.lower() not in {"pdf", "docx", "txt", "doc"}:
        raise ResumeExtractionError("unsupported_file_type", "Upload a PDF, DOCX, or TXT resume file.")
    return f"{base}.{extension.lower()}"


def _extract_pdf(content: bytes, max_pages: int) -> tuple[str, int]:
    if not content.startswith(b"%PDF-"):
        raise ResumeExtractionError("malformed_pdf", "The uploaded PDF is malformed or does not match its file type.")
    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise ResumeExtractionError(
                "encrypted_pdf", "Password-protected PDFs cannot be read. Upload an unencrypted PDF instead."
            )
        page_count = len(reader.pages)
        if page_count == 0:
            raise ResumeExtractionError("malformed_pdf", "The uploaded PDF has no pages.")
        if page_count > max_pages:
            raise ResumeExtractionError("pdf_page_limit", "The uploaded PDF exceeds the 100-page limit.")
        return "\n\n".join((page.extract_text() or "") for page in reader.pages), page_count
    except ResumeExtractionError:
        raise
    except Exception:
        raise ResumeExtractionError("malformed_pdf", "The uploaded PDF could not be read safely.") from None


def _extract_docx(content: bytes) -> str:
    _validate_docx_archive(content)
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = Document(BytesIO(content))
        blocks: list[str] = []
        for child in document.element.body.iterchildren():
            if child.tag.endswith("}p"):
                paragraph = Paragraph(child, document)
                value = paragraph.text.strip()
                if value:
                    prefix = "- " if paragraph.style and paragraph.style.name.lower().startswith("list") else ""
                    blocks.append(f"{prefix}{value}")
            elif child.tag.endswith("}tbl"):
                table = Table(child, document)
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                    if cells:
                        blocks.append(" | ".join(cells))
        return "\n".join(blocks)
    except ResumeExtractionError:
        raise
    except Exception:
        raise ResumeExtractionError("docx_extraction_failure", "The DOCX document could not be read safely.") from None


def _validate_docx_archive(content: bytes) -> None:
    try:
        with ZipFile(BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > MAX_DOCX_MEMBERS:
                raise ResumeExtractionError("unsafe_docx_archive", "The DOCX archive is too complex to process safely.")
            total_size = 0
            names: set[str] = set()
            for member in members:
                path = PurePosixPath(member.filename)
                if path.is_absolute() or ".." in path.parts or "\\" in member.filename:
                    raise ResumeExtractionError("unsafe_docx_archive", "The DOCX archive contains an unsafe file path.")
                if member.file_size > MAX_DOCX_MEMBER_BYTES:
                    raise ResumeExtractionError("unsafe_docx_archive", "The DOCX archive contains an oversized file.")
                total_size += member.file_size
                if total_size > MAX_DOCX_UNCOMPRESSED_BYTES:
                    raise ResumeExtractionError(
                        "unsafe_docx_archive", "The DOCX archive is too large to process safely."
                    )
                if member.compress_size and member.file_size / member.compress_size > 200:
                    raise ResumeExtractionError("unsafe_docx_archive", "The DOCX archive cannot be processed safely.")
                names.add(member.filename)
            if "word/document.xml" not in names or "[Content_Types].xml" not in names:
                raise ResumeExtractionError("malformed_docx", "The uploaded DOCX is missing required document content.")
            if any(name.lower().endswith("vbaproject.bin") for name in names):
                raise ResumeExtractionError("unsafe_docx_archive", "Macro-enabled documents are not supported.")
    except ResumeExtractionError:
        raise
    except (BadZipFile, OSError):
        raise ResumeExtractionError("malformed_docx", "The uploaded DOCX is malformed.") from None


def _extract_text(content: bytes) -> str:
    if _looks_binary(content):
        raise ResumeExtractionError("binary_txt", "The TXT file appears to contain binary data.")
    try:
        if content.startswith((b"\xff\xfe", b"\xfe\xff")):
            return content.decode("utf-16")
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        match = from_bytes(content).best()
        if match is None or not match.encoding or match.percent_coherence < 30:
            raise ResumeExtractionError("undecodable_txt", "The TXT file could not be decoded safely.") from None
        try:
            return str(match)
        except Exception:
            raise ResumeExtractionError("undecodable_txt", "The TXT file could not be decoded safely.") from None


def _looks_binary(content: bytes) -> bool:
    if not content:
        return False
    if content.count(b"\x00") > max(1, len(content) // 100):
        return True
    controls = sum(byte < 9 or 14 <= byte < 32 for byte in content)
    return controls / len(content) > 0.02


def _safe_mime_type(extension: str) -> str:
    return {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain",
    }[extension]
