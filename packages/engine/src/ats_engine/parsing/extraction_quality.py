from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

"""Deterministic, content-agnostic scoring for competing PDF text extractions.

When more than one extraction library can read the same PDF, their outputs
often differ in fidelity: one may glue a decorative contact icon onto the
following email address, another may insert missing spaces between adjacent
text runs correctly. This module scores each candidate on structural signals
only — never on candidate-content relevance — so the pipeline can pick the
most faithful extraction without ever looking at what the resume says.
"""

_SECTION_HEADINGS = (
    "summary",
    "profile",
    "experience",
    "employment",
    "work history",
    "education",
    "skills",
    "certifications",
    "certificates",
)

# A run of 2+ lowercase letters immediately followed by an uppercase letter
# then a lowercase letter is the fingerprint of two words glued together by a
# missing space ("usingPostgreSQL"). Genuine camelCase/branded terms produce
# the same signal in every candidate extraction of the same document, so this
# is used only to compare candidates against each other, never as an absolute
# threshold.
_GLUED_WORD_PATTERN = re.compile(r"[a-z]{2,}[A-Z][a-z]")

# A bullet marker immediately followed by non-space text: the PDF-extraction
# fingerprint this pipeline specifically had to repair (see document_extraction).
_GLUED_BULLET_PATTERN = re.compile(r"(?:^|\n)\s*[\-*•][A-Za-z]")

# Recognizes an email/URL match whose immediately preceding character is
# neither whitespace, line-start, nor a conventional resume separator
# (|, ·, (, :, -) — the fingerprint of a decorative contact icon glued
# directly onto the following contact value with no space at all.
_CONTACT_PATTERNS = [
    re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?:https?://)?(?:www\.)?[A-Za-z0-9-]+\.[A-Za-z]{2,}(?:/[^\s|]*)?"),
]
_SAFE_PRECEDING_CHARS = set(" \n\t|·-(:@")


@dataclass(frozen=True, slots=True)
class ExtractionQualityScore:
    """Structural quality signals for one extraction candidate."""

    method: str
    score: float
    replacement_chars: int
    private_use_chars: int
    control_chars: int
    glued_word_count: int
    glued_bullet_count: int
    glued_contact_prefix_count: int
    single_char_line_count: int
    section_headings_found: int
    char_count: int
    line_count: int
    manual_review_recommended: bool


def score_extraction(method: str, text: str) -> ExtractionQualityScore:
    """Score one candidate extraction on structural fidelity signals only."""
    replacement_chars = text.count("�")
    private_use_chars = sum(1 for ch in text if 0xE000 <= ord(ch) <= 0xF8FF)
    control_chars = sum(1 for ch in text if ch not in "\n\t" and unicodedata.category(ch) == "Cc")
    glued_word_count = len(_GLUED_WORD_PATTERN.findall(text))
    glued_bullet_count = len(_GLUED_BULLET_PATTERN.findall(text))
    glued_contact_prefix_count = _count_glued_contact_prefixes(text)

    lines = text.split("\n")
    single_char_line_count = sum(1 for line in lines if len(line.strip()) == 1)
    lowered = text.lower()
    section_headings_found = sum(1 for heading in _SECTION_HEADINGS if heading in lowered)

    score = (
        float(section_headings_found) * 2.0
        - float(replacement_chars) * 5.0
        - float(private_use_chars) * 5.0
        - float(control_chars) * 3.0
        - float(glued_word_count) * 1.5
        - float(glued_bullet_count) * 2.0
        - float(glued_contact_prefix_count) * 4.0
        - float(single_char_line_count) * 0.5
    )

    manual_review_recommended = bool(
        replacement_chars or private_use_chars or glued_contact_prefix_count or glued_bullet_count > 2
    )

    return ExtractionQualityScore(
        method=method,
        score=score,
        replacement_chars=replacement_chars,
        private_use_chars=private_use_chars,
        control_chars=control_chars,
        glued_word_count=glued_word_count,
        glued_bullet_count=glued_bullet_count,
        glued_contact_prefix_count=glued_contact_prefix_count,
        single_char_line_count=single_char_line_count,
        section_headings_found=section_headings_found,
        char_count=len(text),
        line_count=len(lines),
        manual_review_recommended=manual_review_recommended,
    )


def select_best_extraction(
    candidates: list[tuple[str, str]],
) -> tuple[str, str, ExtractionQualityScore]:
    """Score every ``(method, text)`` candidate and return the best one.

    ``candidates`` must contain at least one entry. Ties keep the first
    (highest-priority) candidate, so callers should order candidates from
    most to least generally trusted.
    """
    scored = [(method, text, score_extraction(method, text)) for method, text in candidates]
    best_method, best_text, best_score = max(scored, key=lambda item: item[2].score)
    return best_method, best_text, best_score


def _count_glued_contact_prefixes(text: str) -> int:
    count = 0
    for pattern in _CONTACT_PATTERNS:
        for match in pattern.finditer(text):
            if match.start() == 0:
                continue
            preceding = text[match.start() - 1]
            if preceding not in _SAFE_PRECEDING_CHARS:
                count += 1
    return count
