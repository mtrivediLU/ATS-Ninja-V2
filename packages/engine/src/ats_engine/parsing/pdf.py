from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def extract_text_from_pdf(uploaded_file: Any) -> str:
    """Extract text from all pages of a PDF file-like object or path.

    :mod:`pdfplumber` is imported lazily so that importing the engine (or using
    the many code paths that operate on already-extracted text) does not require
    the PDF stack to be installed or loaded.
    """
    if uploaded_file is None:
        return ""

    try:
        import pdfplumber
    except ImportError:  # pragma: no cover - pdfplumber is a declared dependency
        logger.error("pdfplumber is not installed; cannot extract PDF text.")
        return ""

    try:
        if hasattr(uploaded_file, "seek"):
            uploaded_file.seek(0)

        with pdfplumber.open(uploaded_file) as pdf:
            page_text = [
                _clean_extracted_text(page.extract_text(x_tolerance=1, y_tolerance=3) or page.extract_text() or "")
                for page in pdf.pages
            ]

        return "\n\n".join(text.strip() for text in page_text if text.strip()).strip()
    except Exception:
        logger.exception("Failed to extract text from PDF.")
        return ""
    finally:
        try:
            if hasattr(uploaded_file, "seek"):
                uploaded_file.seek(0)
        except Exception:
            logger.debug("Unable to reset uploaded PDF pointer.", exc_info=True)


def clean_extracted_text(text: str) -> str:
    """Public wrapper for normalizing text extracted from tightly formatted PDFs."""
    return _clean_extracted_text(text)


def _clean_extracted_text(text: str) -> str:
    """Normalize text extracted from tightly formatted resume PDFs."""
    if not text:
        return ""

    cleaned = text.replace("\x00", "")
    cleaned = re.sub(r"([A-Za-z])-\n([A-Za-z])", r"\1\2", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return _merge_wrapped_lines(cleaned.strip())


def _merge_wrapped_lines(text: str) -> str:
    """Rejoin sentences that the PDF layout hard-wrapped across visual lines.

    Resume bullets routinely span two or three PDF lines. Downstream parsing
    treats each line as a unit, so an unmerged continuation line gets misread as
    a new entry or employer. A continuation is detected conservatively: the
    current line starts with a lowercase letter (or digit) and the previous line
    has content and does not end with terminal punctuation typical of a
    completed heading or field.
    """
    merged: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            merged.append("")
            continue
        previous = merged[-1] if merged else ""
        if _is_wrapped_continuation(previous, line):
            merged[-1] = f"{previous} {line}"
        else:
            merged.append(line)
    return "\n".join(merged)


def _is_wrapped_continuation(previous: str, line: str) -> bool:
    if not previous or not line:
        return False
    if previous.endswith((".", "!", "?", ":", ";", "|")):
        return False
    if re.match(r"^[\-*•]", line):
        return False
    if _looks_like_section_heading(line) or _looks_like_dated_heading(line):
        return False

    previous_is_bullet = bool(re.match(r"^\s*[\-*•]", previous))
    if previous_is_bullet:
        return True

    return line[0].islower() or line[0].isdigit() or previous.endswith((",", "(", "/", "&"))


def _looks_like_section_heading(line: str) -> bool:
    normalized = re.sub(r"\s+", " ", line.strip()).upper()
    return normalized in {
        "PROFESSIONAL SUMMARY",
        "SUMMARY",
        "TECHNICAL SKILLS",
        "SKILLS",
        "PROFESSIONAL EXPERIENCE",
        "EXPERIENCE",
        "EDUCATION",
        "CERTIFICATIONS",
        "LICENSES",
    }


def _looks_like_dated_heading(line: str) -> bool:
    return bool(
        re.search(
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\s*(?:-|to|–|—)\s*(?:Present|Current|\w+\s+\d{4}|\d{4})",
            line,
            flags=re.IGNORECASE,
        )
        or re.search(r"\b\d{4}\s*(?:-|to|–|—)\s*(?:Present|Current|\d{4})\b", line, flags=re.IGNORECASE)
    )
