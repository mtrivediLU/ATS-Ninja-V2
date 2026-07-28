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

from ats_engine.parsing.extraction_quality import ExtractionQualityScore, select_best_extraction

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
    extraction_engine: str = ""
    manual_review_recommended: bool = False


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
    extraction_engine = ""
    manual_review_recommended = False
    if extension == "doc":
        raise ResumeExtractionError(
            "legacy_doc_unsupported",
            "Legacy .doc files are not supported yet. Save the document as .docx, PDF, or plain text and try again.",
        )
    if extension == "pdf":
        if mime_type not in PDF_MIME_TYPES:
            raise ResumeExtractionError("unsupported_file_type", "The file type does not match a PDF document.")
        text, page_count, extraction_engine, quality = _extract_pdf_multi_engine(content, max_pdf_pages)
        manual_review_recommended = quality.manual_review_recommended
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
    warnings = (
        ("Extraction quality: manual review of the extracted text is recommended before continuing.",)
        if manual_review_recommended
        else ()
    )
    return ResumeExtraction(
        filename=safe_filename,
        mime_type=_safe_mime_type(extension),
        size_bytes=len(content),
        extraction_method=method,
        text=normalized,
        character_count=len(normalized),
        page_count=page_count,
        warnings=warnings,
        extraction_engine=extraction_engine,
        manual_review_recommended=manual_review_recommended,
    )


_BULLET_MARKER_NO_GAP = re.compile(r"^(\s*[\-*•])([A-Za-z])", flags=re.MULTILINE)
# A leading numeric hyphen (``-5%``) is a value, not a bullet marker.  Treating
# it as a bullet can incorrectly merge the following physical line into a
# numeric statement during PDF cleanup.
_WRAP_BULLET = re.compile(r"^\s*[\-*•]\s*(?!\d)\S")
_WRAP_SECTION = re.compile(
    r"^(?:professional\s+)?(?:summary|experience|professional experience|work experience|education|"
    r"certifications?|technical skills|skills|projects?|publications?)\s*:?$",
    flags=re.IGNORECASE,
)
_WRAP_DATE = re.compile(r"\b(?:19|20)\d{2}\b")


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
    normalized = _repair_glued_skill_words(normalized)
    normalized = _join_wrapped_bullet_lines(normalized)
    return re.sub(r"\n{4,}", "\n\n\n", normalized).strip()


def _join_wrapped_bullet_lines(text: str) -> str:
    """Join extraction-only continuations back into their preceding bullet.

    PDF engines commonly emit an orphan line for a visually wrapped bullet. A
    continuation is safe to join only while the preceding line is a bullet,
    does not already end a sentence, and the next line is neither a bullet,
    recognised section heading, nor date-bearing header. This intentionally
    preserves ordinary resume line structure while keeping fragments such as
    ``Cloud SQL Auth Proxy, configuring ...`` attached to their source bullet.
    """
    lines = text.split("\n")
    joined: list[str] = []
    for line in lines:
        stripped = line.strip()
        previous = joined[-1].strip() if joined else ""
        can_join = (
            bool(previous)
            and bool(stripped)
            and _WRAP_BULLET.match(previous) is not None
            and _WRAP_BULLET.match(stripped) is None
            and _WRAP_SECTION.match(stripped) is None
            and _WRAP_DATE.search(stripped) is None
            and previous[-1:] not in {".", "!", "?", ":"}
        )
        if can_join:
            joined[-1] = f"{joined[-1].rstrip()} {stripped}"
        else:
            joined.append(line)
    return "\n".join(joined)


# A local, generic "Label: rest-of-line" line-shape gate for the skills-line
# glued-word repair below. Deliberately broad (it will also match e.g.
# "Credential ID: ..." lines) -- safety comes entirely from the exact-match
# tables below, not from this gate, since this module has no cross-section
# awareness (section parsing is a later, separate stage in `parsing.resume`).
_SKILL_LABEL_LINE = re.compile(r"^(?P<label>[A-Za-z][A-Za-z0-9&/ ,'.-]{0,48}):\s*(?P<items>\S.*)$")

# Curated, exact-match fixes for column-extraction glued words observed in
# skills lines (missing inter-word spacing from tight/zero-width kerning
# between styled spans, e.g. a bold label immediately followed by regular
# text -- a different defect class from the hyphen wraps above, no hyphen
# involved at all). Exact-match only, by design: "prefer a curated
# vocabulary-driven split over a general heuristic" -- a general
# lower-upper-boundary splitter would also mangle genuine camelCase brand
# names like "ZoomInfo"/"PowerPoint"/"GitHub" (see `_KNOWN_SINGLE_TOKENS`).
_GLUED_LABEL_FIXES = {
    "Databases&DataEngineering": "Databases & Data Engineering",
    "BI&DataGovernance": "BI & Data Governance",
}
_GLUED_ITEM_FIXES = {
    "MSSQLServer": "MS SQL Server",
    "DataWarehousing": "Data Warehousing",
    "DataModeling": "Data Modeling",
    "ETL/ELTPipelines": "ETL/ELT Pipelines",
}
# Never split by construction (the repair below only ever consults the two
# exact-match tables above; nothing outside them is ever touched). Kept as an
# explicit list purely so a test can assert every one of these round-trips
# unchanged, proving the point by construction rather than by chance.
_KNOWN_SINGLE_TOKENS = frozenset(
    {
        "PostgreSQL",
        "JavaScript",
        "PowerShell",
        "ArcGIS",
        "SharePoint",
        "GitHub",
        "DevOps",
        "MySQL",
        "SQLite",
        "IoT",
        "iOS",
        "ZoomInfo",
    }
)
_BARE_AMPERSAND = re.compile(r"([A-Za-z])&([A-Za-z])")


def _space_bare_ampersand(line: str) -> str:
    def _join(match: re.Match[str]) -> str:
        before, after = match.group(1), match.group(2)
        if before.isupper() and after.isupper():
            return match.group(0)  # e.g. "AT&T" -- both immediate neighbours
            # uppercase; leave a short brand alone rather than space it out.
        return f"{before} & {after}"

    return _BARE_AMPERSAND.sub(_join, line)


# Matches a recognized glued label immediately after an optional bullet
# marker -- e.g. a bullet's own lead-in category ("• BI&DataGovernance: ...")
# as well as a bare skills-section label. Narrower than `_SKILL_LABEL_LINE`
# on purpose: it only ever rewrites the label substring itself (an exact
# match from `_GLUED_LABEL_FIXES`), leaving everything else on the line --
# bulleted prose included -- completely untouched.
_BULLETED_GLUED_LABEL = re.compile(
    r"^(?P<prefix>\s*[\-*•]\s*)(?P<label>" + "|".join(re.escape(key) for key in _GLUED_LABEL_FIXES) + r"):"
)


def _repair_glued_skill_words(text: str) -> str:
    """Repair column-extraction glued words in "Label: item, item" lines.

    Conservative by design: only the curated exact-match tables above are
    ever rewritten, plus two purely mechanical, vocabulary-free fixes (a
    missing space after a comma, and a bare "&" spaced out). A false split
    that mangles a real product name is worse than leaving a glued word, so
    anything not in the curated tables is left exactly as extracted -- this
    intentionally does not attempt to fully de-glue a run-on line that has no
    comma/ampersand boundary to anchor a safe split (e.g. a fully
    space-stripped bullet); only its recognizable label/item tokens are
    fixed, and everything else survives unchanged (no fact is lost).
    """
    lines = text.split("\n")
    for index, line in enumerate(lines):
        bulleted_label = _BULLETED_GLUED_LABEL.match(line)
        if bulleted_label is not None:
            fixed = _GLUED_LABEL_FIXES[bulleted_label.group("label")]
            lines[index] = f"{bulleted_label.group('prefix')}{fixed}:{line[bulleted_label.end() :]}"
            continue

        match = _SKILL_LABEL_LINE.match(line)
        if match is None:
            continue
        label = match.group("label").strip()
        items = match.group("items")
        fixed_label = _GLUED_LABEL_FIXES.get(label, label)
        fixed_items = ",".join(_GLUED_ITEM_FIXES.get(item.strip(), item) for item in items.split(","))
        rebuilt = f"{fixed_label}: {fixed_items}"
        rebuilt = _space_bare_ampersand(rebuilt)
        rebuilt = re.sub(r",(?=\S)", ", ", rebuilt)
        lines[index] = rebuilt
    return "\n".join(lines)


def _validate_filename(filename: str | None) -> str:
    if not filename or len(filename) > 255 or "\x00" in filename or "/" in filename or "\\" in filename:
        raise ResumeExtractionError("unsupported_file_type", "Upload a PDF, DOCX, or TXT resume file.")
    if filename.startswith(".") or filename.count(".") != 1:
        raise ResumeExtractionError("unsupported_file_type", "Upload a PDF, DOCX, or TXT resume file.")
    base, extension = filename.rsplit(".", 1)
    if not base or extension.lower() not in {"pdf", "docx", "txt", "doc"}:
        raise ResumeExtractionError("unsupported_file_type", "Upload a PDF, DOCX, or TXT resume file.")
    return f"{base}.{extension.lower()}"


_LINE_BREAK_HYPHEN = re.compile(r"([A-Za-z]+)-\s*\n\s*([A-Za-z])")

# A curated list of hyphenated-compound lead-in words: when a PDF's line wrap
# happens to land exactly on one of these words' own hyphen ("non-\ntechnical",
# "well-\nknown"), the hyphen is part of the word and must be KEPT; every
# other wrap fragment ("Zoom-\nInfo", "stake-\nholders", "specifi-\ncations",
# "opera-\ntional") is not a standalone word on its own and the hyphen must be
# DROPPED. Exact (not prefix) match against this list is the safety property
# here -- e.g. "co" is listed but "com" (from "Com-\nmerce") is a different
# string and does not match it.
_HYPHEN_WRAP_KEEP_PREFIXES = frozenset(
    {
        "non",
        "well",
        "real",
        "multi",
        "self",
        "co",
        "e",
        "re",
        "pre",
        "post",
        "sub",
        "inter",
        "cross",
        "full",
        "part",
        "end",
        "off",
        "on",
        "long",
        "short",
        "high",
        "low",
        "state",
        "user",
        "data",
        "service",
        "b2b",
        "b2c",
    }
)


def _join_hyphen_wrap(match: re.Match[str]) -> str:
    prefix, next_char = match.group(1), match.group(2)
    if prefix.casefold() in _HYPHEN_WRAP_KEEP_PREFIXES:
        return f"{prefix}-{next_char}"
    return f"{prefix}{next_char}"


def _repair_line_break_hyphens(text: str) -> str:
    """Join a word split only by a PDF-native end-of-line hyphen ("Hi-\\nbernate").

    Fires only when the hyphen is immediately followed by a line break — the
    unambiguous PDF signal for a word-wrap break — so a legitimate mid-line
    hyphenated compound (well-known, end-to-end, multi-language) is never
    touched: those never have a literal newline between the hyphen and the
    next letter. When the wrap happens to land on a curated hyphenated-compound
    lead-in word's own hyphen (e.g. "non-\\ntechnical"), the hyphen is kept
    ("non-technical") instead of dropped ("nontechnical").
    """
    return _LINE_BREAK_HYPHEN.sub(_join_hyphen_wrap, text)


_SPACE_HYPHEN_COMPOUND = re.compile(
    r"\b(" + "|".join(sorted(_HYPHEN_WRAP_KEEP_PREFIXES, key=len, reverse=True)) + r")-[ \t]+(?=[a-z])",
    flags=re.IGNORECASE,
)


def _repair_hyphen_space_wraps(text: str) -> str:
    """Tighten "prefix- word" to "prefix-word" for a curated compound lead-in.

    Unlike `_repair_line_break_hyphens`, a hyphen followed only by ordinary
    whitespace (no literal newline) is NOT an unambiguous wrap signal on its
    own -- `_repair_line_break_hyphens("well- known") == "well- known"` is an
    intentional, tested invariant of that function. This is therefore a
    separate, narrower repair: it only ever closes the gap for a prefix
    already in the same curated keep-list, so it can never join two unrelated
    words and never drops a hyphen -- it is keep-only, not keep-or-drop.
    """
    return _SPACE_HYPHEN_COMPOUND.sub(r"\1-", text)


def _repair_hyphen_wraps(text: str) -> str:
    """Both hyphen-wrap repairs, applied to one per-candidate extraction."""
    return _repair_hyphen_space_wraps(_repair_line_break_hyphens(text))


def _extract_pdf_multi_engine(content: bytes, max_pages: int) -> tuple[str, int, str, ExtractionQualityScore]:
    """Extract PDF text with multiple engines and select the highest-fidelity result.

    ``pypdf`` is the mandatory, already-hardened validation path (encryption,
    page-count, and page-limit checks all happen here and their errors are
    authoritative). PyMuPDF and pdfplumber are additional best-effort text
    candidates only: a PDF that pypdf accepts but one of them cannot read is
    not an error, that candidate is just dropped from the pool. Selection uses
    only structural fidelity signals (see ``extraction_quality``), never
    candidate-content relevance.
    """
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
        pypdf_text = _repair_hyphen_wraps("\n\n".join((page.extract_text() or "") for page in reader.pages))
    except ResumeExtractionError:
        raise
    except Exception:
        raise ResumeExtractionError("malformed_pdf", "The uploaded PDF could not be read safely.") from None

    candidates: list[tuple[str, str]] = [("pypdf", pypdf_text)]
    pymupdf_text = _extract_pdf_pymupdf(content, page_count)
    if pymupdf_text is not None:
        candidates.append(("pymupdf", _repair_hyphen_wraps(pymupdf_text)))
    pdfplumber_text = _extract_pdf_pdfplumber(content)
    if pdfplumber_text is not None:
        candidates.append(("pdfplumber", _repair_hyphen_wraps(pdfplumber_text)))

    method, text, quality = select_best_extraction(candidates)
    return text, page_count, method, quality


def _extract_pdf_pymupdf(content: bytes, expected_page_count: int) -> str | None:
    """Best-effort PyMuPDF candidate. Returns ``None`` on any failure or mismatch."""
    try:
        import fitz
    except ImportError:  # pragma: no cover - pymupdf is a declared dependency
        return None
    try:
        with fitz.open(stream=content, filetype="pdf") as document:
            if document.is_encrypted or document.page_count != expected_page_count:
                return None
            return "\n\n".join(page.get_text("text") for page in document)
    except Exception:
        return None


def _extract_pdf_pdfplumber(content: bytes) -> str | None:
    """Best-effort pdfplumber candidate. Returns ``None`` on any failure."""
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover - pdfplumber is a declared dependency
        return None
    try:
        with pdfplumber.open(BytesIO(content)) as document:
            return "\n\n".join(
                (page.extract_text(x_tolerance=1, y_tolerance=3) or page.extract_text() or "")
                for page in document.pages
            )
    except Exception:
        return None


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
